/// Кастомная тема из файла: %APPDATA%\nekochat\theme.json.
/// Возвращает содержимое файла или None, если файла нет.
#[tauri::command]
fn read_theme_file() -> Option<String> {
    let appdata = std::env::var_os("APPDATA")?;
    let path = std::path::PathBuf::from(appdata).join("nekochat").join("theme.json");
    std::fs::read_to_string(path).ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![read_theme_file])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}