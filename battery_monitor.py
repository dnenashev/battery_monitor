#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Battery Monitor for MacBook

This program monitors battery status and application energy consumption on a MacBook,
displaying information in the terminal to help users manage battery life.
"""

import os
import sys
import time
import subprocess
import curses
import datetime
import re
import json
from collections import defaultdict

# Try to import required libraries
try:
    import psutil
except ImportError:
    print("Установка необходимых библиотек...")
    subprocess.call([sys.executable, "-m", "pip", "install", "psutil"])
    import psutil

try:
    from Foundation import NSBundle
    import objc
except ImportError:
    print("Установка необходимых библиотек...")
    subprocess.call([sys.executable, "-m", "pip", "install", "pyobjc"])
    from Foundation import NSBundle
    import objc

# We'll use psutil for battery information instead of IOKit
# psutil is already imported above

# Global variables
app_energy_usage = defaultdict(float)  # Cumulative energy usage per app
previous_app_energy = {}  # Previous energy readings per app
battery_history = []  # History of battery percentage for graph
start_time = time.time()  # Program start time


def get_battery_info():
    """
    Get battery information from macOS system using psutil.
    Returns a dictionary with battery percentage, capacity, and power usage.
    """
    try:
        # Get battery information using psutil
        battery = psutil.sensors_battery()
        if not battery:
            return None
            
        # Extract basic battery information
        percentage = battery.percent
        is_charging = battery.power_plugged
        time_to_empty = battery.secsleft if battery.secsleft > 0 else 0
        
        # Set default values for information not directly available through psutil
        design_capacity = 5760  # Default design capacity in mAh
        max_capacity = 5572    # Default max capacity in mAh
        voltage = 10.8  # More accurate MacBook voltage (typically 10.8V to 11.4V)
        temperature = 25.0  # Default temperature
        cycle_count = 0
        current_amperage = 0.0  # Current amperage in mA
        instant_power = 0.0  # Instantaneous power in mW
        
        # Try to get actual battery capacity using ioreg command
        try:
            ioreg_output = subprocess.run(['ioreg', '-r', '-c', 'AppleSmartBattery'], capture_output=True, text=True)
            ioreg_text = ioreg_output.stdout
            
            # Extract design capacity
            design_capacity_match = re.search(r'"DesignCapacity" = (\d+)', ioreg_text)
            if design_capacity_match:
                design_capacity = int(design_capacity_match.group(1))
                
            # Extract max capacity
            max_capacity_match = re.search(r'"AppleRawMaxCapacity" = (\d+)', ioreg_text)
            if max_capacity_match:
                max_capacity = int(max_capacity_match.group(1))
                
            # Extract cycle count
            cycle_count_match = re.search(r'"CycleCount" = (\d+)', ioreg_text)
            if cycle_count_match:
                cycle_count = int(cycle_count_match.group(1))
                
            # Extract voltage (in mV, convert to V)
            voltage_match = re.search(r'"Voltage" = (\d+)', ioreg_text)
            if voltage_match:
                voltage = int(voltage_match.group(1)) / 1000.0
                
            # Extract temperature (in 0.1°C, convert to °C)
            temp_match = re.search(r'"Temperature" = (\d+)', ioreg_text)
            if temp_match:
                temperature = int(temp_match.group(1)) / 100.0
                
            # Extract current amperage (in mA)
            amperage_match = re.search(r'"InstantAmperage" = (-?\d+)', ioreg_text)
            if amperage_match:
                current_amperage = abs(int(amperage_match.group(1)))
                
            # Calculate instantaneous power (in mW)
            if voltage > 0 and current_amperage > 0:
                instant_power = (voltage * current_amperage) / 1000.0  # Convert to W
        except Exception as e:
            # If ioreg fails, we'll use the default values set above
            pass
        
        # Try to get more detailed information if available
        try:
            import subprocess
            import json
            result = subprocess.run(['system_profiler', 'SPPowerDataType', '-json'], capture_output=True, text=True)
            power_data = json.loads(result.stdout)
            
            if 'SPPowerDataType' in power_data and len(power_data['SPPowerDataType']) > 0:
                battery_info = power_data['SPPowerDataType'][0].get('sppower_battery_info', {})
                if battery_info:
                    cycle_count = battery_info.get('sppower_battery_cycle_count', 0)
                    temperature = battery_info.get('sppower_battery_temperature', 25.0)
        except:
            pass  # Fallback to default values if system_profiler fails
        
        # Calculate power usage using real-time data when available
        if instant_power > 0:
            # Use the instantaneous power we calculated from voltage and amperage
            power_usage = instant_power
        elif time_to_empty > 0 and not is_charging:
            # If instant power not available, estimate based on battery level and time to empty
            hours_left = time_to_empty / 3600
            # Calculate power based on remaining capacity and time
            remaining_capacity_wh = (percentage / 100) * max_capacity * voltage
            power_usage = remaining_capacity_wh / hours_left
        else:
            # Try to get power data from pmset
            try:
                pmset_output = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True)
                pmset_text = pmset_output.stdout
                power_match = re.search(r'(\d+\.\d+)W', pmset_text)
                if power_match:
                    power_usage = float(power_match.group(1))
                else:
                    # Default power usage estimate if all else fails
                    power_usage = 8.0  # More conservative MacBook power usage in watts
            except:
                # Default power usage estimate if all else fails
                power_usage = 8.0  # More conservative MacBook power usage in watts
                print("Using default power value 8.0W")
        
        # Calculate current capacity in mWh
        current_mwh = (percentage / 100) * max_capacity * voltage
        max_mwh = max_capacity * voltage
        
        # Calculate remaining time in hours and minutes
        if not is_charging and time_to_empty > 0:
            remaining_hours = time_to_empty // 3600  # Convert seconds to hours
            remaining_minutes = (time_to_empty % 3600) // 60  # Convert remainder to minutes
        else:
            remaining_hours = 0
            remaining_minutes = 0
        
        return {
            "percentage": percentage,
            "current_mwh": current_mwh,
            "max_mwh": max_mwh,
            "power_usage": power_usage,
            "is_charging": is_charging,
            "remaining_hours": remaining_hours,
            "remaining_minutes": remaining_minutes,
            "temperature": temperature,
            "cycle_count": cycle_count
        }
    except Exception as e:
        print(f"Ошибка при получении информации о батарее: {e}")
        return None


def get_app_energy_usage():
    """
    Get energy usage per application using powermetrics and psutil.
    Returns a dictionary with app names and their current power usage in watts,
    energy impact score, and 12-hour consumption estimate.
    """
    try:
        # Initialize default structure
        app_energy = defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            '12h_consumption_wh': 0.0
        })
        total_cpu_percent = 0
        process_to_app_map = {}

    except Exception as e:
        print(f"Error in energy usage collection: {e}")
        return defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            '12h_consumption_wh': 0.0
        })
    
    try:
        # Try to get energy data using powermetrics (more accurate, requires sudo)
        use_powermetrics = False
        powermetrics_data = {}
        
        try:
            # Try to run powermetrics with a short sampling period
            powermetrics_cmd = ['powermetrics', '-n', '1', '-i', '1000', '--show-process-energy', '--format', 'json']
            
            # Check if we have permission to run powermetrics
            try:
                powermetrics_result = subprocess.run(powermetrics_cmd, capture_output=True, text=True, timeout=3)
            except PermissionError:
                print("Warning: Insufficient permissions for powermetrics. Falling back to psutil data.")
                powermetrics_result = None
            
            if powermetrics_result and powermetrics_result.returncode == 0:
                try:
                    power_data = json.loads(powermetrics_result.stdout)
                    if 'processor' in power_data and 'tasks' in power_data:
                        use_powermetrics = True
                        total_energy_impact = sum(task.get('energy_impact', 0) for task in power_data['tasks'])
                        
                        # Only use energy impact data if we have meaningful values
                        if total_energy_impact > 0:
                            for task in power_data['tasks']:
                                if 'name' in task and 'energy_impact' in task and 'pid' in task:
                                    pid = task['pid']
                                    name = task['name']
                                    energy_impact = task['energy_impact']
                                    powermetrics_data[pid] = {
                                        'name': name,
                                        'energy_impact': energy_impact
                                    }
                except json.JSONDecodeError as e:
                    print(f"Error decoding powermetrics JSON: {e}")
        except (subprocess.SubprocessError, TimeoutError) as e:
            print(f"Powermetrics failed: {e}. Using psutil fallback.")
        
        # Build a mapping of process names to application names
        try:
            # Use system_profiler to get application names
            apps_cmd = ['system_profiler', 'SPApplicationsDataType', '-json']
            apps_result = subprocess.run(apps_cmd, capture_output=True, text=True)
            
            if apps_result.returncode == 0:
                apps_data = json.loads(apps_result.stdout)
                if 'SPApplicationsDataType' in apps_data:
                    for app_info in apps_data['SPApplicationsDataType']:
                        if 'path' in app_info and '_name' in app_info:
                            app_name = app_info['_name']
                            app_path = app_info['path']
                            app_bundle = os.path.basename(app_path)
                            process_to_app_map[app_bundle] = app_name
            else:
                print(f"No command line for PID {pid}")
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as e:
            # Continue without application name mapping
            pass
            
        # Get process information using psutil
        # Make sure we have a valid process iterator
        processes = []
        try:
            processes = list(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'cmdline']))
        except Exception as e:
            print(f"Error getting process list: {e}")
            processes = []
            
        # Ensure we have a valid processes list
        if processes is None or not processes:
            print("No valid processes found to analyze")
            processes = []
            
        for proc in processes:
            try:
                # Get process info and validate it has required fields
                proc_info = proc.as_dict(attrs=['pid', 'name', 'cpu_percent', 'memory_info', 'cmdline'])
                if not proc_info or 'pid' not in proc_info or 'name' not in proc_info:
                    continue
                    
                pid = proc_info['pid']
                name = proc_info['name']
                
                # Skip system processes
                if name.startswith('_') or name == 'kernel_task':
                    continue
                
                # Try to get a more user-friendly application name
                app_name = name
                
                # Check if we have a mapping for this process
                if name in process_to_app_map:
                    app_name = process_to_app_map[name]
                else:
                    # Try to extract app name from process command line
                    cmdline = proc_info.get('cmdline', [])
                    cmdline = proc_info.get('cmdline') or []
                for cmd in cmdline:
                        if cmd and '.app/' in cmd:
                            app_bundle = cmd.split('.app/')[0].split('/')[-1] + '.app'
                            if app_bundle in process_to_app_map:
                                app_name = process_to_app_map[app_bundle]
                                break
                
                # Update CPU usage
                proc.cpu_percent(interval=None)
                total_cpu_percent += proc_info['cpu_percent']
                
                # Group by application name
                # Check if memory_info is available
                memory_mb = 0
                if proc_info.get('memory_info') is not None:
                    memory_mb = proc_info['memory_info'].rss / (1024 * 1024)
                
                if app_name not in app_energy:
                    app_energy[app_name] = {
                        'cpu_percent': proc_info.get('cpu_percent', 0),
                        'memory_mb': memory_mb,
                        'pids': [pid]
                    }
                    
                    # Add powermetrics data if available
                    if use_powermetrics and pid in powermetrics_data:
                        app_energy[app_name]['energy_impact'] = powermetrics_data[pid]['energy_impact']
                else:
                    app_energy[app_name]['cpu_percent'] += proc_info.get('cpu_percent', 0)
                    
                    # Check if memory_info is available
                    if proc_info.get('memory_info') is not None:
                        app_energy[app_name]['memory_mb'] += proc_info['memory_info'].rss / (1024 * 1024)
                    
                    app_energy[app_name]['pids'].append(pid)
                    
                    # Add powermetrics data if available
                    if use_powermetrics and pid in powermetrics_data:
                        if 'energy_impact' in app_energy[app_name]:
                            app_energy[app_name]['energy_impact'] += powermetrics_data[pid]['energy_impact']
                        else:
                            app_energy[app_name]['energy_impact'] = powermetrics_data[pid]['energy_impact']
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    
        # Get battery info to estimate total power usage
        battery_info = get_battery_info()
        
        # Default power value if battery info is not available or total_cpu_percent is zero
        default_power = 10.0  # Default power in watts
        
        # Get total power from battery info or use default
        total_power = default_power
        if battery_info:
            total_power = battery_info['power_usage']
        
        # Calculate total memory usage for all processes
        total_memory_mb = 0
        if app_energy:
            try:
                total_memory_mb = sum(app_data.get('memory_mb', 0) for app_data in app_energy.values())
            except Exception as e:
                print(f"Error calculating total memory: {e}")
        
        # If no app data was collected, return empty defaultdict instead of empty dict
        if not app_energy:
            print("No application energy data collected. Check permissions or try running with sudo.")
            return defaultdict(lambda: {
                'power_watts': 0.0,
                'energy_impact_score': 0,
                '12h_consumption_wh': 0.0
            })
            
        # Process application energy usage
        for app_name, app_data in app_energy.items():
            # If we have energy impact from powermetrics, use it to calculate power
            if use_powermetrics and 'energy_impact' in app_data:
                # Convert energy impact to power (watts)
                # Energy impact is a relative score, we scale it to match total power
                # Safely calculate total energy impact with proper error handling
                total_energy_impact = 0
                if app_energy and isinstance(app_energy, dict):
                    for app_info in app_energy.values():
                        if app_info is not None and isinstance(app_info, dict):
                            total_energy_impact += app_info.get('energy_impact', 0)
                if total_energy_impact > 0:
                    power_ratio = app_data['energy_impact'] / total_energy_impact
                    app_data['power_watts'] = total_power * power_ratio
                else:
                    # Fallback to CPU/memory based calculation
                    app_data['power_watts'] = 0.1  # Minimal power usage
            else:
                # Weight CPU usage more heavily than memory (80% CPU, 20% memory)
                if total_cpu_percent > 0 and total_memory_mb > 0:
                    cpu_weight = 0.8
                    memory_weight = 0.2
                    
                    cpu_ratio = app_data['cpu_percent'] / total_cpu_percent
                    memory_ratio = app_data['memory_mb'] / total_memory_mb
                    
                    # Combined weighted ratio
                    power_ratio = (cpu_ratio * cpu_weight) + (memory_ratio * memory_weight)
                elif total_cpu_percent > 0:
                    # If memory data unreliable, use only CPU
                    power_ratio = app_data['cpu_percent'] / total_cpu_percent
                else:
                    # If no CPU usage detected, distribute power evenly
                    power_ratio = 1.0 / max(1, len(app_energy))
                    
                app_data['power_watts'] = total_power * power_ratio
            
            # Calculate energy impact score (similar to Activity Monitor)
            # This is a simplified version of Apple's algorithm
            cpu_impact = app_data['cpu_percent'] * 0.7  # CPU has high impact
            memory_impact = (app_data['memory_mb'] / max(1, total_memory_mb)) * 100 * 0.3  # Memory has lower impact
            app_data['energy_impact_score'] = int(cpu_impact + memory_impact)
            
            # Calculate energy impact (Wh) for the last interval
            interval = 10  # seconds
            app_data['energy_wh'] = app_data['power_watts'] * (interval / 3600)
            
            # Update cumulative energy usage
            if app_name in previous_app_energy:
                energy_diff = app_data['power_watts'] * (interval / 3600)
                app_energy_usage[app_name] += energy_diff
            
            # Calculate 12-hour consumption estimate (Wh)
            app_data['consumption_12h'] = app_data['power_watts'] * 12
            
            # Calculate time impact (how much time would be saved if app is closed)
            # Use safe values to avoid division by zero
            current_mwh = 1000.0  # Default value
            if battery_info and 'current_mwh' in battery_info and battery_info['current_mwh'] > 0:
                current_mwh = battery_info['current_mwh']
            
            # Ensure power_watts exists and is greater than zero
            power_watts = app_data.get('power_watts', 0)
            if power_watts > 0:
                try:
                    time_impact_hours = power_watts / (current_mwh / 1000)
                    app_data['time_impact_hours'] = time_impact_hours
                    app_data['time_impact_minutes'] = time_impact_hours * 60
                except Exception:
                    # Fallback if calculation fails
                    app_data['time_impact_hours'] = 0
                    app_data['time_impact_minutes'] = 0
            else:
                app_data['time_impact_hours'] = 0
                app_data['time_impact_minutes'] = 0
            
        # Update previous energy readings
        previous_app_energy.clear()
        for app_name, app_data in app_energy.items():
            if 'power_watts' in app_data:
                previous_app_energy[app_name] = app_data['power_watts']
            
    except Exception as e:
        print(f"Error collecting app energy data: {e}")
        import traceback
        traceback.print_exc()
        return defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            '12h_consumption_wh': 0.0
        })


def draw_battery_graph(stdscr, history, max_width):
    """
    Draw an ASCII graph of battery percentage over time.
    """
    try:
        if not history:
            return
        
        # Get actual window dimensions
        max_y, max_x = stdscr.getmaxyx()
        
        # Determine graph dimensions (ensure we stay within window bounds)
        height = min(5, max_y - 3)  # Leave room for labels
        width = min(len(history), max_width - 10, max_x - 6)  # Leave room for y-axis labels
        
        # Skip if not enough space or data points
        if width < 2 or height < 3:
            stdscr.addstr(0, 0, "Недостаточно места для отображения графика")
            return
        
        # Calculate y-coordinates for each point
        max_val = 100  # Battery percentage max is 100%
        min_val = max(0, min(p for p in history) - 5)  # Min value with some padding
        
        # Sample points to fit the width
        if len(history) > width:
            step = len(history) / width
            points = [history[int(i * step)] for i in range(width)]
        else:
            points = history[-width:]
        
        # Draw graph frame (with boundary checks)
        if 0 < max_y and max_x > 30:
            stdscr.addstr(0, 0, "Заряд батареи за время работы:")
        
        # Draw y-axis labels (with boundary checks)
        if 1 < max_y and max_x > 5:
            stdscr.addstr(1, 0, f"{max_val}%")
        if height < max_y and max_x > 5:
            stdscr.addstr(height, 0, f"{min_val}%")
        
        # Draw x-axis (with boundary checks)
        for i in range(width):
            if i + 5 < max_x and height + 1 < max_y:
                stdscr.addstr(height + 1, i + 5, "_")
        
        # Draw x-axis labels (with boundary checks)
        elapsed_minutes = int((time.time() - start_time) / 60)
        if height + 2 < max_y and 5 < max_x:
            stdscr.addstr(height + 2, 5, "0m")
        if height + 2 < max_y and width + 3 < max_x:
            stdscr.addstr(height + 2, width + 3, f"{elapsed_minutes}m")
        
        # Draw data points (with boundary checks)
        for i, point in enumerate(points):
            # Calculate y position (inverted because terminal coordinates increase downward)
            y_pos = height - int((point - min_val) / (max_val - min_val) * (height - 1))
            y_pos = max(1, min(height, y_pos))  # Ensure within bounds
            
            # Draw the point if within screen bounds
            if i + 5 < max_x and y_pos < max_y:
                try:
                    stdscr.addstr(y_pos, i + 5, "*")
                except curses.error:
                    # Silently ignore curses errors when drawing points
                    pass
    except Exception as e:
        # Safely display error message with boundary check
        try:
            max_y, max_x = stdscr.getmaxyx()
            if 1 < max_y and max_x > 30:
                stdscr.addstr(1, 0, f"Ошибка при отрисовке графика: {str(e)[:max_x-30]}")
        except:
            # Last resort if even error display fails
            pass
        return


def main(stdscr):
    """
    Main function to run the battery monitor program.
    """
    # Setup curses
    curses.curs_set(0)  # Hide cursor
    curses.start_color()
    curses.use_default_colors()
    stdscr.timeout(1000)  # Set getch() timeout to 1 second
    
    # Define color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # Green for good battery
    curses.init_pair(2, curses.COLOR_YELLOW, -1)  # Yellow for medium battery
    curses.init_pair(3, curses.COLOR_RED, -1)  # Red for low battery
    curses.init_pair(4, curses.COLOR_CYAN, -1)  # Cyan for headers
    
    # Main loop
    update_interval = 10  # seconds
    last_update = 0
    
    while True:
        # Check for key press
        key = stdscr.getch()
        if key == ord('q'):
            break
        
        current_time = time.time()
        
        # Update every 10 seconds
        if current_time - last_update >= update_interval:
            # Clear screen
            stdscr.clear()
            
            # Get battery information
            battery_info = get_battery_info()
            if not battery_info:
                stdscr.addstr(0, 0, "Не удалось получить информацию о батарее.")
                stdscr.refresh()
                time.sleep(1)
                continue
            
            # Add battery percentage to history
            battery_history.append(battery_info['percentage'])
            
            # Keep history at a reasonable size
            max_history = 1000
            if len(battery_history) > max_history:
                battery_history.pop(0)
            
            # Get application energy usage
            app_energy = get_app_energy_usage()
            
            # Ensure app_energy is not None before using it
            if app_energy is None:
                app_energy = {}
            
            # Display battery information
            battery_percent = battery_info['percentage']
            color = curses.color_pair(1) if battery_percent > 50 else \
                   curses.color_pair(2) if battery_percent > 20 else \
                   curses.color_pair(3)
            
            # Current time
            current_datetime = datetime.datetime.now().strftime("%H:%M:%S")
            stdscr.addstr(0, 0, f"Время: {current_datetime} | Нажмите 'q' для выхода", curses.color_pair(4))
            
            # Battery status
            stdscr.addstr(2, 0, "СОСТОЯНИЕ БАТАРЕИ:", curses.color_pair(4))
            stdscr.addstr(3, 0, f"Заряд: {battery_percent:.1f}% ({battery_info['current_mwh']:.0f} mWh / {battery_info['max_mwh']:.0f} mWh)")
            
            # Remaining time
            if battery_info['is_charging']:
                stdscr.addstr(4, 0, "Статус: Заряжается")
            else:
                stdscr.addstr(4, 0, f"Осталось: {battery_info['remaining_hours']} часов {battery_info['remaining_minutes']} минут")
            
            stdscr.addstr(5, 0, f"Потребление: {battery_info['power_usage']:.2f} Вт | Температура: {battery_info['temperature']:.1f}°C")
            
            # Display application energy usage
            stdscr.addstr(7, 0, "ПОТРЕБЛЕНИЕ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ:", curses.color_pair(4))
            stdscr.addstr(8, 0, "Приложение                  Энергия  Текущее (Вт)  За 12ч (Вт·ч)  Влияние на время")
            
            # Sort apps by energy impact score if available, otherwise by power usage
            if app_energy and any('energy_impact_score' in app_data for _, app_data in app_energy.items()):
                sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('energy_impact_score', 0), reverse=True)
            else:
                sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('power_watts', 0), reverse=True)
            
            # Display top energy-consuming apps
            row = 9
            for app_name, app_data in sorted_apps[:15]:  # Show top 15 apps
                try:
                    # Skip invalid app data
                    if not isinstance(app_data, dict):
                        continue
                        
                    # Format app name (truncate if too long)
                    app_name_fmt = str(app_name)[:25].ljust(25)
                    
                    # Energy impact score
                    energy_impact = app_data.get('energy_impact_score', 0)
                    energy_impact_fmt = f"{energy_impact}".rjust(5)
                    
                    # Current power usage
                    current_power = app_data.get('power_watts', 0)
                    current_power_fmt = f"{current_power:.2f}".rjust(8)
                    
                    # 12-hour consumption estimate
                    consumption_12h = app_data.get('consumption_12h', 0)
                    consumption_12h_fmt = f"{consumption_12h:.1f}".rjust(10)
                    
                    # Time impact
                    time_impact_minutes = app_data.get('time_impact_minutes', 0)
                    if time_impact_minutes >= 60:
                        time_impact_fmt = f"{time_impact_minutes/60:.1f} ч".rjust(10)
                    else:
                        time_impact_fmt = f"{time_impact_minutes:.1f} мин".rjust(10)
                except Exception as e:
                    # Skip this app if there's an error processing its data
                    continue
                
                # Display app info with color based on energy impact
                app_color = curses.color_pair(1) if energy_impact < 20 else \
                           curses.color_pair(2) if energy_impact < 50 else \
                           curses.color_pair(3)
                
                stdscr.addstr(row, 0, app_name_fmt)
                stdscr.addstr(row, 26, energy_impact_fmt, app_color)
                stdscr.addstr(row, 33, current_power_fmt)
                stdscr.addstr(row, 45, consumption_12h_fmt)
                stdscr.addstr(row, 58, time_impact_fmt)
                
                row += 1
            
            # Draw battery graph
            graph_start_row = row + 2
            stdscr.addstr(graph_start_row, 0, "ГРАФИК ЗАРЯДА БАТАРЕИ:", curses.color_pair(4))
            max_width = curses.COLS - 1 if curses.COLS > 0 else 80
            draw_battery_graph(stdscr.derwin(graph_start_row + 1, 0), battery_history, max_width)
            
            # Program runtime
            runtime = time.time() - start_time
            runtime_hours = int(runtime // 3600)
            runtime_minutes = int((runtime % 3600) // 60)
            runtime_seconds = int(runtime % 60)
            stdscr.addstr(curses.LINES - 1, 0, f"Время работы программы: {runtime_hours:02d}:{runtime_minutes:02d}:{runtime_seconds:02d}")
            
            # Update last update time
            last_update = current_time
            
            # Refresh screen
            stdscr.refresh()
        
        # Small sleep to reduce CPU usage
        time.sleep(0.1)


if __name__ == "__main__":
    try:
        # Run the main function with curses wrapper
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("Программа завершена пользователем.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")