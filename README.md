# Gemini — Asistente de Voz Local para Windows

Asistente de escritorio estilo Jarvis llamado **Gemini** que corre en segundo plano (System Tray) escuchando tu voz sin encender la cámara ni el LED.

## Cómo usarlo

1. **Palabra clave ("Gemini"):** Di en voz natural, por ejemplo:
   - *"Gemini, pausa la música"* / *"Gemini, siguiente canción"*
   - *"Gemini, sube el volumen"* / *"Gemini, baja el volumen"* / *"Gemini, silencia el sonido"*
   - *"Gemini, abre Chrome"* / *"Gemini, abre YouTube"* / *"Gemini, busca en YouTube música lofi"*
   - *"Gemini, abre Spotify"* / *"Gemini, abre Obsidian"* / *"Gemini, abre VS Code"*
   - *"Gemini, minimiza todo"* / *"Gemini, cambia de ventana"* / *"Gemini, captura de pantalla"*
   - *"Gemini, qué hora es"* / *"Gemini, segundo plano"*
2. **Atajos globales:**
   - **`Ctrl + Alt + G`**: Hablar directo sin decir *"Gemini"* (*Push-to-Talk*).
   - **`Ctrl + Alt + M`**: Silenciar / Activar micrófono.
   - **`Ctrl + Alt + H`**: Mostrar / Ocultar panel visual.
3. **IA Conversacional (Opcional):**
   - Pega tu `GEMINI_API_KEY` en el panel inferior y haz clic en **Guardar Key** para responder cualquier pregunta general con `gemini-2.5-flash` y leerla en voz alta.

## Ejecución

- **Sin ventana de consola (panel + 2do plano en Tray):** doble clic en `start_jarvis_bg.vbs`.
- **Con consola de diagnóstico:** ejecutar `start_jarvis_debug.bat` o `.venv\Scripts\python.exe main.py`.
