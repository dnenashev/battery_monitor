#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Battery Discharge Analyzer

Анализирует файл battery_discharge_data.json и выявляет приложения,
потребляющие больше всего энергии во время событий высокого разряда.
"""

import json
import datetime
from collections import defaultdict
import argparse
import os
import sys
from tabulate import tabulate  # Для красивого форматирования таблиц (pip install tabulate)
import matplotlib.pyplot as plt  # Для визуализации (pip install matplotlib)

def parse_timestamp(timestamp_str):
    """Преобразует строку ISO timestamp в объект datetime."""
    try:
        return datetime.datetime.fromisoformat(timestamp_str)
    except ValueError:
        # Совместимость со старыми форматами
        try:
            return datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%f")
        except ValueError:
            return datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")

def analyze_high_discharge_events(json_file):
    """Анализирует события высокого разряда и выявляет энергоёмкие приложения."""
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Ошибка: Файл {json_file} не найден.")
        return None
    except json.JSONDecodeError:
        print(f"Ошибка: Файл {json_file} содержит некорректный JSON.")
        return None
    
    high_discharge_events = data.get('high_discharge_snapshots', [])
    
    if not high_discharge_events:
        print("Не найдено ни одного события высокого разряда в данном файле.")
        return None
    
    # Информация о каждом событии высокого разряда
    events_info = []
    
    # Агрегированная статистика по приложениям
    app_stats = defaultdict(lambda: {
        'count': 0,              # Сколько раз приложение было в моменты высокого разряда
        'total_energy': 0,       # Суммарное потребление энергии
        'max_energy': 0,         # Максимальное потребление энергии
        'avg_energy': 0,         # Среднее потребление энергии
        'total_power': 0,        # Суммарное потребление мощности (Вт)
        'max_power': 0,          # Максимальное потребление мощности
        'timestamps': []         # Временные метки, когда приложение потребляло много энергии
    })
    
    # Анализ каждого события высокого разряда
    for i, event in enumerate(high_discharge_events):
        timestamp = parse_timestamp(event['timestamp'])
        discharge_rate = event.get('discharge_rate', 0)
        applications = event.get('applications', {})
        
        # Если нет данных о приложениях, пропускаем событие
        if not applications:
            continue
        
        # Сортировка приложений по энергопотреблению (по убыванию)
        sorted_apps = sorted(
            [(app, app_data) for app, app_data in applications.items() if isinstance(app_data, dict)],
            key=lambda x: x[1].get('energy', 0),
            reverse=True
        )
        
        # Информация о событии
        event_info = {
            'timestamp': timestamp,
            'discharge_rate': discharge_rate,
            'top_apps': sorted_apps[:5]  # Топ-5 приложений по энергопотреблению
        }
        events_info.append(event_info)
        
        # Обновление агрегированной статистики по приложениям
        for app_name, app_data in sorted_apps:
            if not isinstance(app_data, dict):
                continue
                
            energy = app_data.get('energy', 0)
            power = app_data.get('power_watts', 0)
            
            app_stats[app_name]['count'] += 1
            app_stats[app_name]['total_energy'] += energy
            app_stats[app_name]['max_energy'] = max(app_stats[app_name]['max_energy'], energy)
            app_stats[app_name]['total_power'] += power
            app_stats[app_name]['max_power'] = max(app_stats[app_name]['max_power'], power)
            app_stats[app_name]['timestamps'].append(timestamp)
    
    # Расчет средних значений
    for app_name, stats in app_stats.items():
        if stats['count'] > 0:
            stats['avg_energy'] = stats['total_energy'] / stats['count']
            stats['avg_power'] = stats['total_power'] / stats['count']
    
    # Сортировка приложений по суммарному потреблению энергии
    sorted_apps = sorted(
        [(app_name, stats) for app_name, stats in app_stats.items()],
        key=lambda x: x[1]['total_energy'],
        reverse=True
    )
    
    return {
        'total_events': len(events_info),
        'events': events_info,
        'app_stats': sorted_apps
    }

def print_analysis_results(results):
    """Выводит результаты анализа в читаемом формате."""
    if not results:
        return
    
    print(f"\n=== АНАЛИЗ СОБЫТИЙ ВЫСОКОГО РАЗРЯДА БАТАРЕИ ===")
    print(f"Всего событий высокого разряда: {results['total_events']}")
    
    # Вывод агрегированной статистики по приложениям
    print("\n=== ПРИЛОЖЕНИЯ С НАИБОЛЬШИМ ПОТРЕБЛЕНИЕМ ЭНЕРГИИ ===")
    
    table_data = []
    for app_name, stats in results['app_stats'][:15]:  # Топ-15 приложений
        table_data.append([
            app_name,
            stats['count'],
            f"{stats['total_energy']:.2f}",
            f"{stats['avg_energy']:.2f}",
            f"{stats['max_energy']:.2f}",
            f"{stats['avg_power']:.2f}W"
        ])
    
    headers = ["Приложение", "Событий", "Сумм. энергия", "Сред. энергия", "Макс. энергия", "Сред. мощность"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Вывод детальной информации о каждом событии
    print("\n=== ДЕТАЛИ СОБЫТИЙ ВЫСОКОГО РАЗРЯДА ===")
    for i, event in enumerate(results['events']):
        print(f"\nСобытие #{i+1} - {event['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Скорость разряда: {event['discharge_rate']:.2f} mAh/мин")
        print("Топ приложений:")
        
        event_table = []
        for app_name, app_data in event['top_apps']:
            energy = app_data.get('energy', 0)
            power = app_data.get('power_watts', 0)
            pid = app_data.get('pid', 'N/A')
            event_table.append([app_name, f"{energy:.2f}", f"{power:.2f}W", pid])
        
        print(tabulate(event_table, headers=["Приложение", "Энергия", "Мощность", "PID"], tablefmt="simple"))

def create_visualization(results, output_file=None):
    """Создает визуализацию результатов анализа."""
    if not results or not results['app_stats']:
        return
    
    # Топ-10 приложений для визуализации
    top_apps = results['app_stats'][:10]
    
    # Подготовка данных для графика
    app_names = [app[0] for app in top_apps]
    total_energy = [app[1]['total_energy'] for app in top_apps]
    avg_energy = [app[1]['avg_energy'] for app in top_apps]
    
    # Создание графика
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # График суммарного потребления энергии
    bars1 = ax1.bar(app_names, total_energy, color='royalblue')
    ax1.set_title('Суммарное потребление энергии')
    ax1.set_ylabel('Энергия')
    ax1.set_xticklabels(app_names, rotation=45, ha='right')
    
    # Добавление значений над столбцами
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{height:.1f}', ha='center', va='bottom')
    
    # График среднего потребления энергии
    bars2 = ax2.bar(app_names, avg_energy, color='lightcoral')
    ax2.set_title('Среднее потребление энергии')
    ax2.set_ylabel('Средняя энергия')
    ax2.set_xticklabels(app_names, rotation=45, ha='right')
    
    # Добавление значений над столбцами
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{height:.1f}', ha='center', va='bottom')
    
    plt.tight_layout()
    
    # Сохранение или отображение графика
    if output_file:
        plt.savefig(output_file)
        print(f"График сохранен в файл: {output_file}")
    else:
        plt.show()

def main():
    """Основная функция программы."""
    parser = argparse.ArgumentParser(description='Анализатор высокого разряда батареи')
    parser.add_argument('-f', '--file', default='battery_discharge_data.json',
                        help='Путь к JSON-файлу с данными (по умолчанию: battery_discharge_data.json)')
    parser.add_argument('-v', '--visualize', action='store_true',
                        help='Создать визуализацию результатов')
    parser.add_argument('-o', '--output', help='Путь для сохранения графика (если задан параметр -v)')
    
    args = parser.parse_args()
    
    # Проверка наличия файла
    if not os.path.exists(args.file):
        print(f"Ошибка: Файл {args.file} не найден.")
        return 1
    
    # Анализ данных
    results = analyze_high_discharge_events(args.file)
    
    if results:
        # Вывод результатов
        print_analysis_results(results)
        
        # Создание визуализации, если запрошено
        if args.visualize:
            try:
                create_visualization(results, args.output)
            except ImportError:
                print("Для создания визуализации установите matplotlib: pip install matplotlib")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())