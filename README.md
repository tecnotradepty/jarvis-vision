# Jarvis Vision — Mouse Aéreo & Control por Gestos en Segundo Plano

Motor local de visión por computadora para Windows que funciona de forma **invisible en segundo plano** (bandeja del sistema / System Tray) y convierte tu cámara web en un mouse aéreo fluido estilo Jarvis, con un HUD flotante opcional para calibración.

## Gestos del Mouse Aéreo

| Gesto | Acción |
| :--- | :--- |
| **Mano abierta / Índice extendido** | Mover cursor suavizado (Filtro One-Euro) |
| **Pellizco Pulgar + Índice (toque)** | Clic izquierdo (con estabilización anti-salto) |
| **Pellizco Pulgar + Índice (mantener >220ms)** | Arrastrar y soltar (*Drag & Drop*) |
| **Pellizco Pulgar + Medio** | Clic derecho |
| **Índice + Medio arriba (Anular y Meñique doblados)** | Scroll vertical (sube o baja la mano) |
| **Puño cerrado** | *Clutch* (congela el cursor para reposicionar la mano) |
| **Pellizco Pulgar + Meñique (mantener ~0.8s)** | Alternar modo *Standby* sin usar teclado |

## Atajos Globales

- **`Ctrl + Alt + J`**: Pausar / Reanudar cámara (apaga el LED de la cámara y libera CPU).
- **`Ctrl + Alt + H`**: Mostrar / Ocultar el HUD flotante estilo Jarvis.

## Ejecución

- **Invisible en segundo plano (sin consola):** doble clic en `start_jarvis_bg.vbs`.
- **Con consola de diagnóstico:** ejecutar `start_jarvis_debug.bat` o `.venv\Scripts\python.exe main.py`.
