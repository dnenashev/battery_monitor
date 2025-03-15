import subprocess
import plistlib
import json
from datetime import datetime

# Команда с форматом plist
powermetrics_cmd = ['sudo', 'powermetrics', '-n', '1', '-i', '1000', '--show-process-energy', '--format', 'plist']

# Запускаем команду
process = subprocess.run(
    powermetrics_cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=False  # Вывод в байтах, так как plist бинарный
)

# Проверяем успешность выполнения
if process.returncode == 0:
    # Парсим plist из вывода
    data = plistlib.loads(process.stdout)
    
    # Выводим задачи для проверки
    for task in data.get('tasks', []):
        print(f"Process: {task['name']}, PID: {task['pid']}, Energy Impact: {task['energy_impact']}")
    
    # Преобразуем datetime в строку перед сохранением в JSON
    if 'timestamp' in data and isinstance(data['timestamp'], datetime):
        data['timestamp'] = data['timestamp'].isoformat()  # Преобразуем в ISO-строку, например "2025-03-14T21:28:46+03:00"
    
    # Сохраняем в JSON
    with open('output.json', 'w') as f:
        json.dump(data, f, indent=2)
else:
    print(f"Ошибка: {process.stderr.decode()}")