#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Just Get App Info

This program retrieves and displays energy usage information for running applications on a MacBook.
It's a simplified version of the battery_monitor.py script that only runs once and outputs to console.
"""

import os
import sys
import subprocess
import re
import json
from collections import defaultdict


def parse_powermetrics_text(text_output):
    """
    Parse the text output from powermetrics command when JSON format fails.
    Returns a dictionary with processor and tasks information.
    """
    try:
        # Initialize the structure similar to what we'd get from JSON
        result = {
            'processor': {},
            'tasks': []
        }
        
        # Find the "Running tasks" section
        tasks_section = None
        lines = text_output.split('\n')
        for i, line in enumerate(lines):
            if '*** Running tasks ***' in line:
                tasks_section = i + 2  # Skip the header line
                break
        
        if tasks_section is None:
            print("Could not find 'Running tasks' section in powermetrics output")
            return result
        
        # Parse the column headers
        headers_line = lines[tasks_section]
        if not headers_line.strip():
            # If the line is empty, try the next one
            headers_line = lines[tasks_section + 1]
        
        # Skip to the data lines
        data_start = tasks_section + 2
        
        # Process each task line
        for i in range(data_start, len(lines)):
            line = lines[i].strip()
            if not line or line.startswith('***'):
                # End of tasks section
                break
                
            # Split the line by whitespace, but be smart about it
            # Format is typically: Name ID CPU% User% ... Energy Impact
            parts = re.split(r'\s{2,}', line)
            
            if len(parts) < 2:
                continue  # Not enough data
                
            # Extract task information
            task_name = parts[0].strip()
            
            # Try to extract the ID (PID)
            pid = -1  # Default unknown PID
            if len(parts) > 1:
                try:
                    pid_str = parts[1].strip()
                    pid = int(pid_str)
                except ValueError:
                    # If we can't parse the PID, just continue with the default
                    pass
            
            # Try to extract Energy Impact value (usually the last column)
            energy_impact = 0
            if len(parts) > 2:
                try:
                    # Energy Impact is typically the last column
                    energy_str = parts[-1].strip()
                    energy_impact = float(energy_str)
                except ValueError:
                    # If we can't parse the energy impact, just continue with zero
                    pass
            
            # Add this task to our results
            if task_name and task_name != 'Name' and not task_name.startswith('---'):
                result['tasks'].append({
                    'name': task_name,
                    'pid': pid,
                    'energy_impact': energy_impact
                })
        
        return result
    except Exception as e:
        print(f"Error parsing powermetrics text: {e}")
        import traceback
        traceback.print_exc()
        return {'processor': {}, 'tasks': []}

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
        
        return {
            "percentage": percentage,
            "current_mwh": current_mwh,
            "max_mwh": max_mwh,
            "power_usage": power_usage,
            "is_charging": is_charging,
            "temperature": temperature,
            "cycle_count": cycle_count
        }
    except Exception as e:
        print(f"Ошибка при получении информации о батарее: {e}")
        return None


def get_app_energy_usage():
    """
    Get energy usage per application using powermetrics.
    Returns a dictionary with app names and their current power usage in watts,
    energy impact score, energy_impact_per_s, and 12-hour consumption estimate.
    """
    try:
        # Initialize default structure
        app_energy = defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            'energy_impact_per_s': 0.0,
            'consumption_12h': 0.0
        })
        process_to_app_map = {}

    except Exception as e:
        print(f"Error in energy usage collection: {e}")
        return defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            'energy_impact_per_s': 0.0,
            'consumption_12h': 0.0
        })
    
    try:
        # Get energy data using powermetrics (requires sudo)
        powermetrics_data = {}
        
        try:
            # Run powermetrics with a short sampling period using plist format (exactly like in parsemetrics.py)
            powermetrics_cmd = ['powermetrics', '-n', '1', '-i', '1000', '--show-process-energy', '--format', 'plist']
            
            # Check if we have permission to run powermetrics
            try:
                powermetrics_result = subprocess.run(powermetrics_cmd, capture_output=True, text=False, timeout=3)
            except PermissionError:
                print("Error: Insufficient permissions for powermetrics. Please run with sudo.")
                return defaultdict(lambda: {
                    'power_watts': 0.0,
                    'energy_impact_score': 0,
                    'energy_impact_per_s': 0.0,
                    'consumption_12h': 0.0
                })
            
            if not powermetrics_result or powermetrics_result.returncode != 0:
                print("Error: Failed to run powermetrics. Please run with sudo.")
                return defaultdict(lambda: {
                    'power_watts': 0.0,
                    'energy_impact_score': 0,
                    'energy_impact_per_s': 0.0,
                    'consumption_12h': 0.0
                })
                
            try:
                # Import plistlib for parsing plist format
                import plistlib
                
                try:
                    # Parse the plist data from powermetrics output (exactly like in parsemetrics.py)
                    power_data = plistlib.loads(powermetrics_result.stdout)
                    print("Successfully parsed plist data from powermetrics")
                    
                    # Debug output
                    print(f"\nFound {len(power_data.get('tasks', []))} tasks in powermetrics output")
                        
                    # If we couldn't parse the data at all, return empty results
                    if not power_data:
                        print("Failed to parse powermetrics output in any format.")
                        return defaultdict(lambda: {
                            'power_watts': 0.0,
                            'energy_impact_score': 0,
                            'energy_impact_per_s': 0.0,
                            'consumption_12h': 0.0
                        })
                    
                    # Validate the parsed data
                    if 'tasks' not in power_data:
                        print("Error: Invalid powermetrics data format.")
                        print(f"Available keys in power_data: {list(power_data.keys()) if isinstance(power_data, dict) else 'Not a dictionary'}")
                        return defaultdict(lambda: {
                            'power_watts': 0.0,
                            'energy_impact_score': 0,
                            'energy_impact_per_s': 0.0,
                            'consumption_12h': 0.0
                        })
                        
                    # Get tasks with valid energy impact data
                    valid_tasks = [task for task in power_data['tasks'] 
                                  if 'name' in task and 'energy_impact' in task and task.get('energy_impact', 0) > 0]
                    
                    if not valid_tasks:
                        print("Error: No valid task data with energy impact found.")
                        return defaultdict(lambda: {
                            'power_watts': 0.0,
                            'energy_impact_score': 0,
                            'energy_impact_per_s': 0.0,
                            'consumption_12h': 0.0
                        })
                    
                    # Calculate total energy impact
                    total_energy_impact = sum(task.get('energy_impact', 0) for task in valid_tasks)
                    
                    # Get battery info to estimate total power usage
                    battery_info = get_battery_info()
                    total_power = battery_info['power_usage'] if battery_info else 8.0  # Default to 8W if no battery info
                    
                    # Process each task and add to app_energy dictionary
                    for task in valid_tasks:
                        name = task['name']
                        energy_impact = task.get('energy_impact', 0)
                        energy_impact_per_s = task.get('energy_impact_per_s', 0)
                        
                        # Skip tasks with no energy impact
                        if energy_impact <= 0:
                            continue
                            
                        # Calculate power usage based on energy impact proportion
                        power_proportion = energy_impact / total_energy_impact if total_energy_impact > 0 else 0
                        power_watts = total_power * power_proportion
                        
                        # Add to app_energy dictionary
                        app_energy[name]['energy_impact_score'] = int(energy_impact)
                        app_energy[name]['energy_impact_per_s'] = energy_impact_per_s
                        app_energy[name]['power_watts'] = power_watts
                        app_energy[name]['consumption_12h'] = power_watts * 12
                        
                        # Calculate time impact
                        if battery_info and power_watts > 0:
                            try:
                                current_mwh = battery_info.get('current_mwh', 1000.0)
                                # Ensure we're working with reasonable values
                                if current_mwh > 0 and current_mwh < 100000:  # Sanity check for battery capacity
                                    time_impact_hours = current_mwh / 1000 / power_watts  # Correct formula: capacity/power
                                    app_energy[name]['time_impact_hours'] = time_impact_hours
                                    app_energy[name]['time_impact_minutes'] = time_impact_hours * 60
                                else:
                                    app_energy[name]['time_impact_hours'] = 0
                                    app_energy[name]['time_impact_minutes'] = 0
                            except Exception as e:
                                app_energy[name]['time_impact_hours'] = 0
                                app_energy[name]['time_impact_minutes'] = 0
                        else:
                            app_energy[name]['time_impact_hours'] = 0
                            app_energy[name]['time_impact_minutes'] = 0
                    
                    # Return the app energy data
                    return app_energy
                    
                except Exception as e:
                    print(f"\nError parsing plist data: {e}")
                    import traceback
                    traceback.print_exc()
                    return defaultdict(lambda: {
                        'power_watts': 0.0,
                        'energy_impact_score': 0,
                        'energy_impact_per_s': 0.0,
                        'consumption_12h': 0.0
                    })
            except Exception as e:
                print(f"\nUnexpected error processing powermetrics output: {e}")
                import traceback
                traceback.print_exc()
                return defaultdict(lambda: {
                    'power_watts': 0.0,
                    'energy_impact_score': 0,
                    'consumption_12h': 0.0
                })
        except (subprocess.SubprocessError, TimeoutError) as e:
            print(f"Powermetrics failed: {e}. Please run with sudo.")
            return defaultdict(lambda: {
                'power_watts': 0.0,
                'energy_impact_score': 0,
                'consumption_12h': 0.0
            })
    except Exception as e:
        print(f"Error collecting app energy data: {e}")
        import traceback
        traceback.print_exc()
        return defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            'consumption_12h': 0.0
        })
            
        # Process the energy data for each application
        battery_info = get_battery_info()
        total_power = battery_info['power_usage'] if battery_info else 8.0
        
        # If we have valid powermetrics data, process it
        if powermetrics_data:
            # Calculate total energy impact from all processes
            total_energy_impact = sum(data['energy_impact'] for data in powermetrics_data.values())
            
            # Process each app's energy data
            for app_name, app_data in app_energy.items():
                # Skip if we don't have valid app data
                if not isinstance(app_data, dict):
                    continue
                    
                # Get energy impact if available
                energy_impact = 0
                for pid in app_data.get('pids', []):
                    if pid in powermetrics_data:
                        energy_impact += powermetrics_data[pid]['energy_impact']
                
                # Calculate power usage based on energy impact proportion
                if total_energy_impact > 0:
                    power_proportion = energy_impact / total_energy_impact
                    power_watts = total_power * power_proportion
                else:
                    power_watts = 0
                
                # Store the calculated values
                app_data['energy_impact_score'] = int(energy_impact)
                app_data['power_watts'] = power_watts
                app_data['consumption_12h'] = power_watts * 12
                
                # Calculate time impact (how much time would be saved if app is closed)
                current_mwh = 1000.0  # Default value
                if battery_info and 'current_mwh' in battery_info and battery_info['current_mwh'] > 0:
                    current_mwh = battery_info['current_mwh']
                
                if power_watts > 0:
                    try:
                        time_impact_hours = power_watts / (current_mwh / 1000)
                        app_data['time_impact_hours'] = time_impact_hours
                        app_data['time_impact_minutes'] = time_impact_hours * 60
                    except Exception:
                        app_data['time_impact_hours'] = 0
                        app_data['time_impact_minutes'] = 0
                else:
                    app_data['time_impact_hours'] = 0
                    app_data['time_impact_minutes'] = 0
            
        return app_energy
            
    except Exception as e:
        print(f"Error collecting app energy data: {e}")
        import traceback
        traceback.print_exc()
        return defaultdict(lambda: {
            'power_watts': 0.0,
            'energy_impact_score': 0,
            '12h_consumption_wh': 0.0
        })


def main():
    """Main function to run the app info program once."""
    print("\nПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПОТРЕБЛЕНИИ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ\n")
    
    # Get battery information
    battery_info = get_battery_info()
    if battery_info:
        print(f"СОСТОЯНИЕ БАТАРЕИ:")
        print(f"Заряд: {battery_info['percentage']:.1f}% ({battery_info['current_mwh']:.0f} mWh / {battery_info['max_mwh']:.0f} mWh)")
        
        if battery_info['is_charging']:
            print("Статус: Заряжается")
        
        print(f"Потребление: {battery_info['power_usage']:.2f} Вт | Температура: {battery_info['temperature']:.1f}°C")
        print()
    
    # Get application energy usage
    app_energy = get_app_energy_usage()
    
    if not app_energy or not any(app_energy.values()):
        print("Не удалось получить информацию о потреблении энергии приложениями.")
        return
    
    print("ПОТРЕБЛЕНИЕ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ:")
    print("{:<30} {:>8} {:>12} {:>15} {:>15} {:>15}".format(
        "Приложение", "Энергия", "Энергия/с", "Текущее (Вт)", "За 12ч (Вт·ч)", "Влияние на время"))
    
    # Sort apps by energy impact per second if available, otherwise by energy impact score
    if app_energy and any('energy_impact_per_s' in app_data for _, app_data in app_energy.items()):
        sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('energy_impact_per_s', 0), reverse=True)
    elif app_energy and any('energy_impact_score' in app_data for _, app_data in app_energy.items()):
        sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('energy_impact_score', 0), reverse=True)
    else:
        sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('power_watts', 0), reverse=True)
    
    # Display top energy-consuming apps
    for app_name, app_data in sorted_apps[:20]:  # Show top 20 apps
        try:
            # Skip invalid app data
            if not isinstance(app_data, dict):
                continue
                
            # Format app name (truncate if too long)
            app_name_fmt = str(app_name)[:28]
            
            # Energy impact score
            energy_impact = app_data.get('energy_impact_score', 0)
            
            # Energy impact per second
            energy_impact_per_s = app_data.get('energy_impact_per_s', 0)
            
            # Current power usage
            current_power = app_data.get('power_watts', 0)
            
            # 12-hour consumption estimate
            consumption_12h = app_data.get('consumption_12h', 0)
            
            # Time impact
            time_impact_minutes = app_data.get('time_impact_minutes', 0)
            if time_impact_minutes >= 60:
                time_impact_fmt = f"{time_impact_minutes/60:.1f} ч"
            else:
                time_impact_fmt = f"{time_impact_minutes:.1f} мин"
                
            print("{:<30} {:>8} {:>12.2f} {:>12.2f} {:>15.1f} {:>15}".format(
                app_name_fmt, energy_impact, energy_impact_per_s, current_power, consumption_12h, time_impact_fmt))
                
        except Exception as e:
            # Skip this app if there's an error processing its data
            continue


if __name__ == "__main__":
    main()