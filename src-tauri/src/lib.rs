use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_store::StoreExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
/// CREATE_NO_WINDOW — скрывает консольное окно дочернего процесса на Windows
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

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
    diarize: Option<bool>,
    speakers: Option<u32>,
) {
    let do_diarize = diarize.unwrap_or(false);
    let num_speakers = speakers.unwrap_or(0);
    eprintln!("[start_job] ENTER id={id} model={model} language={language:?} diarize={do_diarize} speakers={num_speakers}");

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
        let model_arg = if model.is_empty() { "base".to_string() } else { model };
        args.extend([
            "--input".to_string(),  input,
            "--output".to_string(), out_dir.to_string_lossy().to_string(),
            "--model".to_string(),  model_arg,
        ]);
        if !language.is_empty() {
            args.extend(["--language".to_string(), language]);
        }
        if do_diarize {
            args.push("--diarize".to_string());
        }
        if do_diarize && num_speakers > 0 {
            args.extend(["--speakers".to_string(), num_speakers.to_string()]);
        }

        eprintln!("[start_job] spawning: {cmd} {:?}", args);

        #[allow(unused_mut)]
        let mut cmd_builder = Command::new(&cmd);
        cmd_builder
            .args(&args)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        cmd_builder.creation_flags(CREATE_NO_WINDOW);
        let child = cmd_builder.spawn();

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

/// Скачивает модель Whisper через Python-сайдкар (--action download-model).
/// Все события (download_progress, download_error) пересылаются во фронтенд.
#[tauri::command]
fn download_model(
    app: AppHandle,
    registry: State<JobRegistry>,
    id: String,
    model: String,
) {
    eprintln!("[download_model] ENTER id={id} model={model}");

    let registry_arc = registry.0.clone();

    thread::spawn(move || {
        let (cmd, mut args) = python_cmd();
        let model_arg = if model.is_empty() { "base".to_string() } else { model };
        args.extend([
            "--action".to_string(),  "download-model".to_string(),
            "--model".to_string(),   model_arg,
        ]);

        eprintln!("[download_model] spawning: {cmd} {:?}", args);

        #[allow(unused_mut)]
        let mut cmd_builder = Command::new(&cmd);
        cmd_builder
            .args(&args)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        cmd_builder.creation_flags(CREATE_NO_WINDOW);
        let child = cmd_builder.spawn();

        match child {
            Err(e) => {
                eprintln!("[download_model] spawn error: {e}");
                emit_event(&app, &id, serde_json::json!({
                    "type": "download_error",
                    "message": format!("Не удалось запустить Python: {e}")
                }));
            }
            Ok(mut child) => {
                let pid = child.id();
                registry_arc.lock().unwrap().insert(id.clone(), pid);
                eprintln!("[download_model] pid={pid}");

                if let Some(stderr) = child.stderr.take() {
                    thread::spawn(move || {
                        for line in BufReader::new(stderr).lines().flatten() {
                            eprintln!("[python dl stderr] {line}");
                        }
                    });
                }

                let mut got_terminal_event = false;

                if let Some(stdout) = child.stdout.take() {
                    for line in BufReader::new(stdout).lines().flatten() {
                        eprintln!("[python dl stdout] {line}");
                        if let Ok(data) = serde_json::from_str::<serde_json::Value>(&line) {
                            let ev_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("?");
                            if ev_type == "download_progress" {
                                let pct = data.get("percent").and_then(|v| v.as_u64()).unwrap_or(0);
                                let status = data.get("status").and_then(|v| v.as_str()).unwrap_or("?");
                                if pct == 100 || status == "complete" || status == "cached" {
                                    got_terminal_event = true;
                                }
                            } else if ev_type == "download_error" {
                                got_terminal_event = true;
                            }
                            emit_event(&app, &id, data);
                        }
                    }
                }

                let exit_status = child.wait();
                registry_arc.lock().unwrap().remove(&id);

                if !got_terminal_event {
                    let code = exit_status
                        .map(|s| s.code().unwrap_or(-1))
                        .unwrap_or(-1);
                    eprintln!("[download_model] ended without terminal event, exit={code}");
                    emit_event(&app, &id, serde_json::json!({
                        "type": "download_error",
                        "message": format!("Процесс завершился неожиданно (код {code}). Возможно, не хватило памяти.")
                    }));
                }

                eprintln!("[download_model] done id={id}");
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

/// Читает значение из %APPDATA%\Transcriber\settings.json
#[tauri::command]
fn get_setting(app: AppHandle, key: String) -> Option<serde_json::Value> {
    app.store("settings.json")
        .ok()
        .and_then(|store| store.get(&key))
}

/// Записывает значение в %APPDATA%\Transcriber\settings.json (сохраняет на диск)
#[tauri::command]
fn set_setting(app: AppHandle, key: String, value: serde_json::Value) {
    if let Ok(store) = app.store("settings.json") {
        store.set(key, value);
        let _ = store.save();
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

fn emit_event(app: &AppHandle, id: &str, data: serde_json::Value) {
    let _ = app.emit("job-event", serde_json::json!({ "id": id, "data": data }));
}

// ── Entry ─────────────────────────────────────────────────────────────────────

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(JobRegistry(Arc::new(Mutex::new(HashMap::new()))))
        .setup(|app| {
            // T9: Удаляем *.partial.json — остатки прерванных сессий
            let out_dir = default_output(app.handle());
            if out_dir.exists() {
                if let Ok(entries) = std::fs::read_dir(&out_dir) {
                    for entry in entries.flatten() {
                        let path = entry.path();
                        if path.extension().and_then(|s| s.to_str()) == Some("json") {
                            let is_partial = path.file_stem()
                                .and_then(|s| s.to_str())
                                .map(|s| s.ends_with(".partial"))
                                .unwrap_or(false);
                            if is_partial {
                                let _ = std::fs::remove_file(&path);
                                eprintln!("[setup] removed stale partial: {:?}", path);
                            }
                        }
                    }
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_job,
            cancel_job,
            download_model,
            get_setting,
            set_setting,
            pick_files,
            pick_folder,
            open_output_folder,
            open_in_explorer,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
