use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter, Manager, State};

// ── State ─────────────────────────────────────────────────────────────────────

/// Хранит PID запущенных Python-процессов — нужен для cancel_job
struct JobRegistry(Arc<Mutex<HashMap<String, u32>>>);

// ── Python path ───────────────────────────────────────────────────────────────

fn python_cmd() -> (String, Vec<String>) {
    #[cfg(debug_assertions)]
    {
        let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("python")
            .join("main.py");
        ("python".to_string(), vec![script.to_string_lossy().to_string()])
    }
    #[cfg(not(debug_assertions))]
    {
        let exe = std::env::current_exe()
            .unwrap_or_default()
            .parent()
            .unwrap_or(&PathBuf::from("."))
            .join("transcriber-core.exe");
        (exe.to_string_lossy().to_string(), vec![])
    }
}

fn default_output(app: &AppHandle) -> PathBuf {
    app.path()
        .document_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("Транскрибатор")
        .join("output")
}

// ── Commands ──────────────────────────────────────────────────────────────────

#[tauri::command]
fn start_job(
    app: AppHandle,
    registry: State<JobRegistry>,
    id: String,
    input: String,
    output: String,
    model: String,
    language: String,
) {
    eprintln!("[start_job] ENTER id={id} model={model} language={language:?}");

    let out_dir = if output.is_empty() {
        default_output(&app)
    } else {
        PathBuf::from(&output)
    };
    std::fs::create_dir_all(&out_dir).ok();

    let registry_arc = registry.0.clone();

    thread::spawn(move || {
        // Имя файла для уведомления (URL обрезаем, путь — только имя файла)
        let display_name = if input.starts_with("http://") || input.starts_with("https://") {
            input.chars().take(60).collect::<String>()
        } else {
            PathBuf::from(&input)
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| input.chars().take(60).collect())
        };

        let (cmd, mut args) = python_cmd();
        let model_arg = if model.is_empty() { "large-v3".to_string() } else { model };
        args.extend([
            "--input".to_string(),  input,
            "--output".to_string(), out_dir.to_string_lossy().to_string(),
            "--model".to_string(),  model_arg,
        ]);
        if !language.is_empty() {
            args.extend(["--language".to_string(), language]);
        }

        eprintln!("[start_job] spawning: {cmd} {:?}", args);

        let child = Command::new(&cmd)
            .args(&args)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();

        match child {
            Err(e) => {
                eprintln!("[start_job] spawn error: {e}");
                emit_event(&app, &id, serde_json::json!({
                    "type": "error",
                    "message": format!("Не удалось запустить Python: {e}")
                }));
            }
            Ok(mut child) => {
                let pid = child.id();
                registry_arc.lock().unwrap().insert(id.clone(), pid);
                eprintln!("[start_job] pid={pid}");

                if let Some(stderr) = child.stderr.take() {
                    thread::spawn(move || {
                        for line in BufReader::new(stderr).lines().flatten() {
                            eprintln!("[python stderr] {line}");
                        }
                    });
                }

                // Флаг: получили ли "done" или "error" от Python.
                // Если нет — процесс упал без сообщения (OOM, SIGKILL и т.п.)
                let mut got_terminal_event = false;
                // Текст для системного уведомления Windows
                let mut notify_body: Option<String> = None;

                if let Some(stdout) = child.stdout.take() {
                    for line in BufReader::new(stdout).lines().flatten() {
                        eprintln!("[python stdout] {line}");
                        if let Ok(data) = serde_json::from_str::<serde_json::Value>(&line) {
                            let ev_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
                            eprintln!("[emit] type={ev_type}");
                            if ev_type == "done" {
                                got_terminal_event = true;
                                notify_body = Some(format!("✓ Готово: {display_name}"));
                            } else if ev_type == "error" {
                                got_terminal_event = true;
                                let msg = data.get("message")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .chars().take(80).collect::<String>();
                                notify_body = Some(format!("✕ {msg}"));
                            }
                            emit_event(&app, &id, data);
                        }
                    }
                }

                let exit_status = child.wait();
                registry_arc.lock().unwrap().remove(&id);

                if !got_terminal_event {
                    // Python упал без emit(error) — OOM, SIGKILL, или другой краш
                    let code = exit_status
                        .map(|s| s.code().unwrap_or(-1))
                        .unwrap_or(-1);
                    eprintln!("[start_job] process ended without terminal event, exit={code}");
                    emit_event(&app, &id, serde_json::json!({
                        "type": "error",
                        "message": format!("Процесс завершился неожиданно (код {code}). Возможно, не хватило памяти.")
                    }));
                    notify_body = Some(format!("✕ {display_name}: неожиданное завершение"));
                }

                // Системное уведомление Windows
                if let Some(body) = notify_body {
                    use tauri_plugin_notification::NotificationExt;
                    let _ = app.notification()
                        .builder()
                        .title("Транскрибатор")
                        .body(&body)
                        .show();
                }

                eprintln!("[start_job] done id={id}");
            }
        }
    });
}

/// Открывает нативный файловый диалог, возвращает список полных путей.
/// Используется вместо HTML <input type="file">, который в WebView2 не отдаёт путь.
#[tauri::command]
async fn pick_files() -> Vec<String> {
    rfd::AsyncFileDialog::new()
        .set_title("Выбрать файлы для транскрипции")
        .add_filter("Медиафайлы", &["mp4","mkv","avi","mov","mp3","wav","m4a","flac","ogg","webm"])
        .pick_files()
        .await
        .unwrap_or_default()
        .into_iter()
        .map(|f| f.path().to_string_lossy().to_string())
        .collect()
}

#[tauri::command]
fn cancel_job(registry: State<JobRegistry>, id: String) {
    eprintln!("[cancel_job] id={id}");
    if let Some(pid) = registry.0.lock().unwrap().remove(&id) {
        eprintln!("[cancel_job] killing pid={pid}");
        // taskkill /F убивает процесс и все дочерние (ffmpeg, python)
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F", "/T"])
            .spawn();
    }
}

#[tauri::command]
async fn pick_folder() -> Option<String> {
    rfd::AsyncFileDialog::new()
        .set_title("Выбрать папку вывода")
        .pick_folder()
        .await
        .map(|f| f.path().to_string_lossy().to_string())
}

#[tauri::command]
fn open_output_folder(app: AppHandle) {
    let path = default_output(&app);
    std::fs::create_dir_all(&path).ok();
    let _ = Command::new("explorer").arg(path).spawn();
}

#[tauri::command]
fn open_in_explorer(path: String) {
    let _ = Command::new("explorer").args(["/select,", &path]).spawn();
}

// ── Helpers ───────────────────────────────────────────────────────────────────

fn emit_event(app: &AppHandle, id: &str, data: serde_json::Value) {
    let _ = app.emit("job-event", serde_json::json!({ "id": id, "data": data }));
}

// ── Entry ─────────────────────────────────────────────────────────────────────

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(JobRegistry(Arc::new(Mutex::new(HashMap::new()))))
        .invoke_handler(tauri::generate_handler![
            start_job,
            cancel_job,
            pick_files,
            pick_folder,
            open_output_folder,
            open_in_explorer,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
