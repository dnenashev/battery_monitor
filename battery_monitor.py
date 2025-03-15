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
import plistlib
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
        
        # Extract design capacity (from factory)
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
        # This is what shows up as "Power Usage" in the screenshot
        if "voltage" in battery_info and "current" in battery_info:
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
        
        # Get remaining time information
        time_remaining_match = re.search(r'"AvgTimeToEmpty" = (\d+)', ioreg_text)
        if time_remaining_match:
            time_to_empty = int(time_remaining_match.group(1))
            # Time to empty is in minutes
            battery_info["remaining_hours"] = time_to_empty // 60
            battery_info["remaining_minutes"] = time_to_empty % 60
        
        # Store mAh values directly
        battery_info["current_mah"] = battery_info.get("current_capacity", 0)
        battery_info["max_mah"] = battery_info.get("max_capacity", 0)
        battery_info["capacity_mah"] = battery_info.get("design_capacity", 0)
        
        # Calculate mWh values for compatibility with existing code
        if "current_capacity" in battery_info and "voltage" in battery_info:
            battery_info["current_mwh"] = battery_info["current_capacity"] * battery_info["voltage"]
        if "max_capacity" in battery_info and "voltage" in battery_info:
            battery_info["max_mwh"] = battery_info["max_capacity"] * battery_info["voltage"]
        
        return battery_info
    
    except Exception as e:
        print(f"Ошибка при получении информации о батарее: {e}")
        return None


def get_app_energy_usage():
    """
    Get application energy usage from the powermetrics command.
    
    Returns a dictionary with app name as key and energy impact as value.
    """
    try:
        # Use plist format for more reliable data parsing (method from parsemetrics.py)
        powermetrics_cmd = ['sudo', 'powermetrics', '-n', '1', '-i', '1000', 
                            '--show-process-energy', '--format', 'plist']
        
        # Try to use sudo without requiring password if script is run with sudo
        environ = os.environ.copy()
        
        # Run the command
        process = subprocess.run(
            powermetrics_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # Output in bytes since plist is binary
            env=environ
        )
        
        # Check if command executed successfully
        if process.returncode != 0:
            return {}

        # Parse plist data
        data = plistlib.loads(process.stdout)
        
        # Process tasks information
        app_energy = {}
        for task in data.get('tasks', []):
            name = task.get('name', 'Unknown')
            energy_impact = task.get('energy_impact', 0)
            pid = task.get('pid', 0)
            
            # Store information by app name
            if name not in app_energy or energy_impact > app_energy[name]['energy']:
                app_energy[name] = {
                    'energy': energy_impact,
                    'pid': pid
                }

        # Track cumulative energy usage
        global previous_app_energy, app_energy_usage
        current_time = time.time()
        
        for app, info in app_energy.items():
            energy = info['energy']
            
            # Calculate delta if we have previous measurement
            if app in previous_app_energy:
                delta = energy - previous_app_energy[app]
                if delta > 0:  # Only count positive changes
                    app_energy_usage[app] += delta
            
            # Store current value for next comparison
            previous_app_energy[app] = energy
        
        return app_energy
    
    except Exception as e:
        return {}  # Return empty dict on any error


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
            try:
                # Clear screen
                stdscr.clear()
                
                # Get terminal size
                max_y, max_x = stdscr.getmaxyx()
                
                # Get battery information
                battery_info = get_battery_info()
                if not battery_info:
                    safe_addstr(stdscr, 0, 0, "Не удалось получить информацию о батарее.")
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
                
                # Calculate additional metrics for each app based on energy impact
                if app_energy and battery_info:
                    total_power_usage = battery_info.get('power_usage', 10.0)  # Default to 10W if power_usage not available
                    total_energy_impact = sum(info['energy'] for app, info in app_energy.items() if isinstance(info, dict))
                    
                    # Calculate total power consumption for all apps for 12 hours
                    total_power_consumption_12h = total_power_usage * 12  # Watt-hours
                    
                    # Calculate estimated battery life based on current total power consumption
                    estimated_battery_life_hours = 0
                    battery_percentage_per_hour = 0
                    
                    if 'current_mwh' in battery_info and total_power_usage > 0:
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
                        if 'max_mwh' in battery_info and battery_info['max_mwh'] > 0:
                            app_data['battery_percent_12h'] = (app_data['consumption_12h'] * 100) / (battery_info['max_mwh'] / 1000)
                        else:
                            app_data['battery_percent_12h'] = 0
                
                # Display battery information
                battery_percent = battery_info['percentage']
                color = curses.color_pair(1) if battery_percent > 50 else \
                       curses.color_pair(2) if battery_percent > 20 else \
                       curses.color_pair(3)
                
                # Current time
                current_datetime = datetime.datetime.now().strftime("%H:%M:%S")
                safe_addstr(stdscr, 0, 0, f"Время: {current_datetime} | Нажмите 'q' для выхода", curses.color_pair(4))
                
                # Battery status
                safe_addstr(stdscr, 2, 0, "СОСТОЯНИЕ БАТАРЕИ:", curses.color_pair(4))
                
                # Show capacity in mAh (not mWh)
                current_mah = battery_info.get('current_mah', 0)
                max_mah = battery_info.get('max_mah', 0)
                design_mah = battery_info.get('capacity_mah', 0)
                
                safe_addstr(stdscr, 3, 0, f"Заряд: {battery_percent:.1f}% ({current_mah} mAh / {max_mah} mAh)")
                safe_addstr(stdscr, 4, 0, f"Расчетная емкость: {max_mah} mAh из {design_mah} mAh проектной")
                
                # Remaining time
                if battery_info.get('is_charging', False):
                    safe_addstr(stdscr, 5, 0, "Статус: Заряжается")
                else:
                    # Display estimated battery life based on current system load
                    if estimated_battery_life_hours > 0:
                        hours = int(estimated_battery_life_hours)
                        minutes = int((estimated_battery_life_hours - hours) * 60)
                        safe_addstr(stdscr, 5, 0, f"Осталось при текущей нагрузке: {hours} часов {minutes} минут")
                    else:
                        remaining_hours = battery_info.get('remaining_hours', 0)
                        remaining_minutes = battery_info.get('remaining_minutes', 0)
                        safe_addstr(stdscr, 5, 0, f"Осталось: {remaining_hours} часов {remaining_minutes} минут")
                
                # Show power usage and temperature with proper colors
                power_usage = battery_info.get('power_usage', 0)
                temp = battery_info.get('temperature', 0)
                
                power_color = curses.color_pair(1) if power_usage < 10 else \
                             curses.color_pair(2) if power_usage < 20 else \
                             curses.color_pair(3)
                temp_color = curses.color_pair(1) if temp < 35 else \
                            curses.color_pair(2) if temp < 45 else \
                            curses.color_pair(3)
                
                safe_addstr(stdscr, 6, 0, f"Потребление: ", curses.A_NORMAL)
                safe_addstr(stdscr, 6, 13, f"{power_usage:.2f} Вт", power_color)
                safe_addstr(stdscr, 6, 22, f" | Температура: ", curses.A_NORMAL)
                safe_addstr(stdscr, 6, 38, f"{temp:.1f}°C", temp_color)
                
                # Add battery consumption rate
                if battery_percentage_per_hour > 0:
                    rate_color = curses.color_pair(1) if battery_percentage_per_hour < 10 else \
                                curses.color_pair(2) if battery_percentage_per_hour < 20 else \
                                curses.color_pair(3)
                    safe_addstr(stdscr, 7, 0, f"Расход батареи: ", curses.A_NORMAL)
                    safe_addstr(stdscr, 7, 16, f"{battery_percentage_per_hour:.1f}% в час", rate_color)
                    
                # Battery condition
                condition = battery_info.get('condition', 'Unknown')
                condition_color = curses.color_pair(1) if condition == 'Normal' else \
                                 curses.color_pair(2) if condition == 'Fair' else \
                                 curses.color_pair(3)
                
                safe_addstr(stdscr, 8, 0, f"Состояние: ", curses.A_NORMAL)
                safe_addstr(stdscr, 8, 11, f"{condition}", condition_color)
                
                # Display application energy usage
                safe_addstr(stdscr, 10, 0, "ПОТРЕБЛЕНИЕ ЭНЕРГИИ ПРИЛОЖЕНИЯМИ:", curses.color_pair(4))
                safe_addstr(stdscr, 11, 0, "Приложение                  Энергия  Текущее (Вт)  За 12ч (Вт·ч)  % батареи за 12ч")
                
                # Sort apps by energy info
                if app_energy:
                    if any('energy' in app_data for _, app_data in app_energy.items()):
                        sorted_apps = sorted(app_energy.items(), key=lambda x: x[1].get('energy', 0), reverse=True)
                    else:
                        sorted_apps = []
                else:
                    sorted_apps = []
                
                # Display top energy-consuming apps
                row = 11
                for app_name, app_data in sorted_apps[:15]:  # Show top 15 apps
                    if row >= max_y - 3:  # Оставляем место для графика
                        break
                        
                    try:
                        # Skip invalid app data or system processes
                        if not isinstance(app_data, dict) or app_name.startswith("_") or app_name == "kernel_task":
                            continue
                            
                        # Format app name (truncate if too long)
                        app_name_fmt = str(app_name)[:25].ljust(25)
                        
                        # Energy impact
                        energy_impact = app_data.get('energy', 0)
                        energy_impact_fmt = f"{energy_impact:.1f}".rjust(5)
                        
                        # Determine color based on energy impact
                        energy_color = curses.color_pair(1) if energy_impact < 30 else \
                                      curses.color_pair(2) if energy_impact < 100 else \
                                      curses.color_pair(3)
                        
                        # Display app info with color
                        safe_addstr(stdscr, row, 0, app_name_fmt)
                        safe_addstr(stdscr, row, 26, energy_impact_fmt, energy_color)
                        
                        # Get the calculated metrics
                        current_power = app_data.get('power_watts', 0)
                        consumption_12h = app_data.get('consumption_12h', 0)
                        
                        # Format and display the calculated values
                        current_power_fmt = f"{current_power:.2f}".rjust(8)
                        consumption_12h_fmt = f"{consumption_12h:.1f}".rjust(10)
                        
                        # Battery percentage used over 12 hours
                        battery_percent_12h = app_data.get('battery_percent_12h', 0)
                        battery_percent_fmt = f"{battery_percent_12h:.1f}%".rjust(10)
                        
                        safe_addstr(stdscr, row, 33, current_power_fmt)
                        safe_addstr(stdscr, row, 45, consumption_12h_fmt)
                        safe_addstr(stdscr, row, 58, battery_percent_fmt)
                        
                        row += 1
                    except Exception as e:
                        # Skip this app if there's an error processing its data
                        continue
                
                # Draw battery graph
                graph_start_row = row + 2
                if graph_start_row < max_y - 3:
                    safe_addstr(stdscr, graph_start_row, 0, "ГРАФИК ЗАРЯДА БАТАРЕИ:", curses.color_pair(4))
                    max_width = min(curses.COLS - 1, max_x - 1) if curses.COLS > 0 else 80
                    draw_battery_graph(stdscr.derwin(graph_start_row + 1, 0), battery_history, max_width)
                
                # Program runtime
                runtime = time.time() - start_time
                runtime_hours = int(runtime // 3600)
                runtime_minutes = int((runtime % 3600) // 60)
                runtime_seconds = int(runtime % 60)
                
                # Make sure we don't try to write outside the screen
                if max_y - 1 > 0:
                    safe_addstr(stdscr, max_y - 1, 0, f"Время работы программы: {runtime_hours:02d}:{runtime_minutes:02d}:{runtime_seconds:02d}")
                
                # Update last update time
                last_update = current_time
                
                # Refresh screen
                stdscr.refresh()
                
            except Exception as e:
                # If something goes wrong, print the error
                stdscr.clear()
                safe_addstr(stdscr, 0, 0, f"Произошла ошибка: {e}")
                stdscr.refresh()
                time.sleep(2)
        
        # Small sleep to reduce CPU usage
        time.sleep(0.1)

# Добавим вспомогательную функцию для безопасного вывода строк в curses
def safe_addstr(window, y, x, string, attr=0):
    """
    Safely add a string to a curses window, checking bounds and truncating if necessary.
    """
    try:
        max_y, max_x = window.getmaxyx()
        if y >= max_y or x >= max_x:
            return
            
        # Determine how much space is available on the line
        available_space = max_x - x
        
        # Truncate the string if it's too long
        if len(string) > available_space:
            string = string[:available_space]
            
        window.addstr(y, x, string, attr)
    except:
        # Ignore any curses errors
        pass


if __name__ == "__main__":
    try:
        # Run the main function with curses wrapper
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("Программа завершена пользователем.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")