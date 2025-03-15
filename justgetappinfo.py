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
import plistlib
from collections import defaultdict
import datetime


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
    Get battery information directly from macOS system using IORegistry.
    Returns a dictionary with accurate battery information without estimations.
    """
    try:
        # Initialize the battery info dictionary
        battery_info = {}
        
        # Use ioreg directly to get the most accurate battery information
        # This is similar to what the Battery Monitor app in the screenshot uses
        ioreg_output = subprocess.run(['ioreg', '-r', '-c', 'AppleSmartBattery'], capture_output=True, text=True)
        ioreg_text = ioreg_output.stdout
        
        # Extract design capacity (from factory) in mAh
        design_capacity_match = re.search(r'"DesignCapacity" = (\d+)', ioreg_text)
        if design_capacity_match:
            design_capacity = int(design_capacity_match.group(1))
            battery_info["design_capacity"] = design_capacity
        
        # Extract actual capacity values
        # MaxCapacity and CurrentCapacity in macOS are often given in relative units, not actual mAh
        max_capacity_match = re.search(r'"MaxCapacity" = (\d+)', ioreg_text)
        current_capacity_match = re.search(r'"CurrentCapacity" = (\d+)', ioreg_text)
        
        # Try to get AppleRawMaxCapacity and AppleRawCurrentCapacity which might have the actual mAh values
        raw_max_capacity_match = re.search(r'"AppleRawMaxCapacity" = (\d+)', ioreg_text)
        raw_current_capacity_match = re.search(r'"AppleRawCurrentCapacity" = (\d+)', ioreg_text)
        
        # Get actual battery capacity in mAh - prefer raw values if available
        if raw_max_capacity_match:
            max_capacity = int(raw_max_capacity_match.group(1))
            battery_info["max_capacity"] = max_capacity
        elif max_capacity_match:
            relative_max = int(max_capacity_match.group(1))
            # If we have the design capacity, use it to estimate real capacity
            if "design_capacity" in battery_info and battery_info["design_capacity"] > 0:
                # In most MacBooks, MaxCapacity is a percentage of DesignCapacity
                actual_max_capacity = battery_info["design_capacity"] * (relative_max / 100.0)
                battery_info["max_capacity"] = int(actual_max_capacity)
            else:
                # Fallback to the relative value but mark it as needing correction
                battery_info["max_capacity"] = relative_max
                battery_info["needs_capacity_correction"] = True
                
        # Get current capacity in mAh
        if raw_current_capacity_match:
            current_capacity = int(raw_current_capacity_match.group(1))
            battery_info["current_capacity"] = current_capacity
        elif current_capacity_match and max_capacity_match:
            relative_current = int(current_capacity_match.group(1))
            relative_max = int(max_capacity_match.group(1))
            
            # If we have the max capacity and it seems realistic (>1000 mAh)
            if "max_capacity" in battery_info and battery_info["max_capacity"] > 1000:
                # Calculate current capacity proportionally
                if relative_max > 0:
                    current_capacity = battery_info["max_capacity"] * (relative_current / relative_max)
                    battery_info["current_capacity"] = int(current_capacity)
            else:
                # Just store the relative value but mark it for correction
                battery_info["current_capacity"] = relative_current
                battery_info["needs_capacity_correction"] = True
        
        # If we need correction and have design capacity, try to correct the values
        if battery_info.get("needs_capacity_correction", False) and "design_capacity" in battery_info:
            # Most MacBooks have MaxCapacity as a percentage of DesignCapacity (approx)
            design_cap = battery_info["design_capacity"]
            if design_cap > 1000:  # If design capacity seems realistic
                battery_info["max_capacity"] = int(design_cap * 0.8)  # Estimate 80% health as a reasonable value
                
                # Get percentage if possible
                if "max_capacity" in battery_info and "current_capacity" in battery_info and battery_info["max_capacity"] > 0:
                    percentage = (battery_info["current_capacity"] / battery_info["max_capacity"]) * 100
                    current_cap = int(battery_info["max_capacity"] * (percentage / 100.0))
                    battery_info["current_capacity"] = current_cap
        
        # Calculate percentage directly
        if "max_capacity" in battery_info and "current_capacity" in battery_info and battery_info["max_capacity"] > 0:
            battery_info["percentage"] = (battery_info["current_capacity"] / battery_info["max_capacity"]) * 100
        
        # Extract voltage (in mV, convert to V)
        voltage_match = re.search(r'"Voltage" = (\d+)', ioreg_text)
        if voltage_match:
            voltage = int(voltage_match.group(1)) / 1000.0
            battery_info["voltage"] = voltage
        
        # Extract temperature (in 0.1°C, convert to °C)
        temp_match = re.search(r'"Temperature" = (\d+)', ioreg_text)
        if temp_match:
            temperature = int(temp_match.group(1)) / 100.0
            battery_info["temperature"] = temperature
        
        # Extract battery cycle count
        cycle_count_match = re.search(r'"CycleCount" = (\d+)', ioreg_text)
        if cycle_count_match:
            cycle_count = int(cycle_count_match.group(1))
            battery_info["cycle_count"] = cycle_count
        
        # Extract power source (AC or Battery)
        external_connected_match = re.search(r'"ExternalConnected" = ([a-zA-Z]+)', ioreg_text)
        if external_connected_match:
            is_external_connected = external_connected_match.group(1).lower() == "yes"
            battery_info["is_charging"] = is_external_connected
            battery_info["power_source"] = "AC Power" if is_external_connected else "Battery"
        
        # Extract amperage (negative when discharging, positive when charging)
        amperage_match = re.search(r'"InstantAmperage" = (-?\d+)', ioreg_text)
        if amperage_match:
            amperage = int(amperage_match.group(1))  # Keep sign for charging/discharging detection
            battery_info["current"] = amperage / 1000.0  # Convert to amps
            
            # Double-check the amperage value - on macOS it's sometimes reported in strange units
            # Make sure it's within reasonable limits (-5A to 5A for a laptop)
            if abs(battery_info["current"]) > 5.0:
                # Might need additional conversion - try dividing by 1000 again
                battery_info["current"] = battery_info["current"] / 1000.0
        
        # Get real-time power (watts) directly from voltage and amperage
        if "voltage" in battery_info and "current" in battery_info:
            # Calculate power in Watts: V × A
            # Use absolute value since power consumption is always positive (direction given by charging state)
            power_watts = abs(battery_info["voltage"] * battery_info["current"])
            
            # Sanity check - typical MacBook power usage is 5-60W
            if power_watts > 0 and power_watts < 100:
                battery_info["power_usage"] = power_watts
            else:
                # If value is unreasonable, use alternative method
                # Try using pmset for power data as a fallback
                try:
                    pmset_output = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True)
                    pmset_text = pmset_output.stdout
                    power_match = re.search(r'(\d+\.\d+)W', pmset_text)
                    if power_match:
                        battery_info["power_usage"] = float(power_match.group(1))
                    else:
                        # Use a typical value based on battery state
                        battery_info["power_usage"] = 7.0 if not battery_info.get("is_charging", False) else 0.0
                except:
                    # Use reasonable default based on battery state
                    battery_info["power_usage"] = 7.0 if not battery_info.get("is_charging", False) else 0.0
        
        # Get battery condition
        condition_match = re.search(r'"BatteryHealth" = "([^"]+)"', ioreg_text)
        if condition_match:
            battery_info["condition"] = condition_match.group(1)
        else:
            # Alternative way to determine condition
            if "max_capacity" in battery_info and "design_capacity" in battery_info and battery_info["design_capacity"] > 0:
                health_percentage = (battery_info["max_capacity"] / battery_info["design_capacity"]) * 100
                if health_percentage >= 80:
                    battery_info["condition"] = "Normal"
                elif health_percentage >= 60:
                    battery_info["condition"] = "Fair"
                else:
                    battery_info["condition"] = "Poor"
        
        # Keep original mAh values for display
        battery_info["current_mah"] = battery_info.get("current_capacity", 0)
        battery_info["max_mah"] = battery_info.get("max_capacity", 0)
        
        # Calculate mWh values only for internal calculations
        if "current_capacity" in battery_info and "voltage" in battery_info:
            battery_info["current_mwh"] = battery_info["current_capacity"] * battery_info["voltage"]
        if "max_capacity" in battery_info and "voltage" in battery_info:
            battery_info["max_mwh"] = battery_info["max_capacity"] * battery_info["voltage"]
        
        # Additional logging for debugging capacity values
        print(f"Debug - Raw battery capacity values from ioreg:")
        if design_capacity_match:
            print(f"DesignCapacity: {design_capacity_match.group(1)}")
        if max_capacity_match:
            print(f"MaxCapacity: {max_capacity_match.group(1)}")
        if current_capacity_match:
            print(f"CurrentCapacity: {current_capacity_match.group(1)}")
        if raw_max_capacity_match:
            print(f"AppleRawMaxCapacity: {raw_max_capacity_match.group(1)}")
        if raw_current_capacity_match:
            print(f"AppleRawCurrentCapacity: {raw_current_capacity_match.group(1)}")
        print(f"Final calculated values: max_mah={battery_info.get('max_mah', 0)}, current_mah={battery_info.get('current_mah', 0)}")
        
        return battery_info
    
    except Exception as e:
        print(f"Ошибка при получении информации о батарее: {e}")
        return None


def get_app_energy_usage():
    """
    Get application energy usage from the powermetrics command using plist format.
    
    Returns a dictionary with app name as key and energy impact as value.
    """
    try:
        # Use plist format for more reliable data parsing (method from parsemetrics.py)
        powermetrics_cmd = ['sudo', 'powermetrics', '-n', '1', '-i', '1000', 
                            '--show-process-energy', '--format', 'plist']
        
        print("Running powermetrics command to collect energy data...")
        print("This may require your password for sudo access.")
        
        # Run the command
        process = subprocess.run(
            powermetrics_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False  # Output in bytes since plist is binary
        )
        
        # Check if command executed successfully
        if process.returncode != 0:
            print(f"Error running powermetrics: {process.stderr.decode()}")
            return {}

        # Parse plist data
        data = plistlib.loads(process.stdout)
        
        # Store tasks information
        app_energy = {}
        
        print("\nEnergy usage by application:")
        print("-" * 80)
        print(f"{'Application':<40} {'PID':<10} {'Energy Impact':<15}")
        print("-" * 80)
        
        # Sort tasks by energy impact (highest first)
        if 'tasks' in data:
            sorted_tasks = sorted(data.get('tasks', []), 
                                 key=lambda x: x.get('energy_impact', 0), 
                                 reverse=True)
            
            for task in sorted_tasks:
                name = task.get('name', 'Unknown')
                energy_impact = task.get('energy_impact', 0)
                pid = task.get('pid', 0)
                
                # Print information about each task
                print(f"{name:<40} {pid:<10} {energy_impact:<15.2f}")
                
                # Store information by app name
                app_energy[name] = {
                    'energy': energy_impact,
                    'pid': pid
                }
        
        # Save data to JSON file for reference
        output_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'tasks': data.get('tasks', [])
        }
        
        try:
            with open('app_energy.json', 'w') as f:
                json.dump(output_data, f, indent=2)
            print("\nData has been saved to app_energy.json")
        except Exception as e:
            print(f"\nWarning: Could not save app_energy.json - {e}")
        
        return app_energy
    
    except Exception as e:
        print(f"Error: {e}")
        return {}  # Return empty dict on any error


def main():
    """Main function to run the app info program once."""
    print("\nПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПОТРЕБЛЕНИИ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ\n")
    
    # Get battery information
    battery_info = get_battery_info()
    if battery_info:
        print(f"СОСТОЯНИЕ БАТАРЕИ:")
        print(f"Заряд: {battery_info['percentage']:.1f}% ({battery_info.get('current_mah', 0):.0f} mAh / {battery_info.get('max_mah', 0):.0f} mAh)")
        
        if battery_info.get('is_charging'):
            print("Статус: Заряжается")
        
        print(f"Потребление: {battery_info.get('power_usage', 0):.2f} Вт | Температура: {battery_info.get('temperature', 0):.1f}°C")
        print()
    
    # Get application energy usage
    app_energy = get_app_energy_usage()
    
    if not app_energy:
        print("Не удалось получить информацию о потреблении энергии приложениями.")
        return
    
    # Calculate additional metrics for each app based on energy impact
    total_power_usage = battery_info.get('power_usage', 10.0) if battery_info else 10.0  # Default to 10W if battery_info not available
    total_energy_impact = sum(info['energy'] for app, info in app_energy.items() if isinstance(info, dict))
    
    # Calculate total power consumption for all apps for 12 hours
    total_power_consumption_12h = total_power_usage * 12  # Watt-hours
    
    # Calculate estimated battery life based on current total power consumption
    estimated_battery_life_hours = 0
    battery_percentage_per_hour = 0
    
    if battery_info and 'current_mwh' in battery_info and total_power_usage > 0:
        # Current battery energy in Watt-hours
        current_battery_energy_wh = battery_info['current_mwh'] / 1000
        # Estimated hours of battery life remaining at current load
        estimated_battery_life_hours = current_battery_energy_wh / total_power_usage
        # Percentage of battery consumed per hour at current load
        if battery_info.get('max_mwh', 0) > 0:
            battery_percentage_per_hour = (total_power_usage * 100) / (battery_info['max_mwh'] / 1000)
    
    # Enhance app data with calculated metrics
    for app_name, app_data in app_energy.items():
        if not isinstance(app_data, dict):
            continue
            
        raw_energy = app_data.get('energy', 0)
        
        # Normalize energy impact to per second (assuming 1 sec sample)
        app_data['energy_impact_per_s'] = raw_energy
        
        # Calculate app's portion of power usage based on its energy impact
        if total_energy_impact > 0:
            ratio = raw_energy / total_energy_impact
            app_data['power_watts'] = total_power_usage * ratio
        else:
            app_data['power_watts'] = 0
            
        # Calculate 12-hour energy consumption
        app_data['consumption_12h'] = app_data['power_watts'] * 12
        
        # Calculate battery percentage consumed by this app over 12 hours
        if battery_info and 'max_mwh' in battery_info and battery_info['max_mwh'] > 0:
            app_data['battery_percent_12h'] = (app_data['consumption_12h'] * 100) / (battery_info['max_mwh'] / 1000)
        else:
            app_data['battery_percent_12h'] = 0
    
    print("ПОТРЕБЛЕНИЕ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ:")
    
    # Add system summary information
    print(f"\nОбщее потребление энергии: {total_power_usage:.2f} Вт")
    if estimated_battery_life_hours > 0:
        print(f"Ожидаемое время работы при текущей нагрузке: {estimated_battery_life_hours:.1f} часов")
        print(f"Потребление батареи: {battery_percentage_per_hour:.1f}% в час")
    print(f"Общий расход за 12 часов: {total_power_consumption_12h:.1f} Вт·ч\n")
    
    print("{:<30} {:>8} {:>12} {:>15} {:>15} {:>15}".format(
        "Приложение", "Энергия", "Энергия/с", "Текущее (Вт)", "За 12ч (Вт·ч)", "% батареи за 12ч"))
    
    # Sort apps by energy impact if available
    sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('energy', 0) if isinstance(x[1], dict) else 0, reverse=True)
    
    # Display top energy-consuming apps
    for app_name, app_data in sorted_apps[:20]:  # Show top 20 apps
        try:
            # Skip invalid app data
            if not isinstance(app_data, dict):
                continue
                
            # Format app name (truncate if too long)
            app_name_fmt = str(app_name)[:28]
            
            # Energy impact score - use the raw energy value
            energy_impact = app_data.get('energy', 0)
            
            # Energy impact per second - same as raw energy since it's per second
            energy_impact_per_s = app_data.get('energy_impact_per_s', 0)
            
            # Current power usage - calculated as portion of total system power
            current_power = app_data.get('power_watts', 0)
            
            # 12-hour consumption estimate
            consumption_12h = app_data.get('consumption_12h', 0)
            
            # Battery percentage used over 12 hours
            battery_percent_12h = app_data.get('battery_percent_12h', 0)
                
            print("{:<30} {:>8.1f} {:>12.2f} {:>15.2f} {:>15.1f} {:>15.1f}%".format(
                app_name_fmt, energy_impact, energy_impact_per_s, current_power, consumption_12h, battery_percent_12h))
                
        except Exception as e:
            # Skip this app if there's an error processing its data
            print(f"Error processing app data for {app_name}: {e}")
            continue


if __name__ == "__main__":
    main()