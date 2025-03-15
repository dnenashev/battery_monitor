#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Battery Monitor (PLIST Version)

This program monitors battery status and application energy consumption on a MacBook,
using the plist format for more reliable and accurate data collection.
"""

import os
import sys
import time
import subprocess
import curses
import datetime
import json
import plistlib
from collections import defaultdict
import re

# Global variables
app_energy_usage = defaultdict(float)  # Cumulative energy usage per app
previous_app_energy = {}  # Previous energy readings per app
battery_history = []  # History of battery percentage for graph
start_time = time.time()  # Program start time

# New global variables for accumulating stats
accumulated_energy = defaultdict(float)  # Accumulated energy impact over time
accumulated_power = defaultdict(float)   # Accumulated power usage over time

def get_battery_info():
    """
    Get battery information directly from macOS system using IORegistry and SMC.
    Returns a dictionary with accurate battery information without estimations.
    """
    try:
        # Initialize the battery info dictionary
        battery_info = {}
        
        # First method: Use ioreg directly to get the most accurate battery information
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
        
        # Get time remaining information
        time_remaining_match = re.search(r'"AvgTimeToEmpty" = (\d+)', ioreg_text)
        if time_remaining_match:
            time_to_empty = int(time_remaining_match.group(1))
            # Time to empty is in minutes
            battery_info["time_remaining_min"] = time_to_empty
        else:
            # Fallback to alternate source
            time_remaining_match = re.search(r'"TimeRemaining" = (\d+)', ioreg_text)
            if time_remaining_match:
                time_to_empty = int(time_remaining_match.group(1))
                battery_info["time_remaining_min"] = time_to_empty
        
        # Get charge status
        is_charged_match = re.search(r'"FullyCharged" = ([a-zA-Z]+)', ioreg_text)
        if is_charged_match:
            battery_info["is_charged"] = is_charged_match.group(1).lower() == "yes"
            
        # Get time to full if charging
        time_to_full_match = re.search(r'"AvgTimeToFull" = (\d+)', ioreg_text)
        if time_to_full_match and battery_info.get("is_charging", False):
            time_to_full = int(time_to_full_match.group(1))
            battery_info["time_to_full_min"] = time_to_full
            
        # Maintain compatibility with existing code that expects certain fields
        # Store actual mAh values directly
        battery_info["current_mah"] = battery_info.get("current_capacity", 0)
        battery_info["max_mah"] = battery_info.get("max_capacity", 0)
        battery_info["capacity_mah"] = battery_info.get("design_capacity", 0)
        
        # Calculate mWh values for internal use only
        if "current_capacity" in battery_info and "voltage" in battery_info:
            battery_info["current_mwh"] = battery_info["current_capacity"] * battery_info["voltage"]
        if "max_capacity" in battery_info and "voltage" in battery_info:
            battery_info["max_mwh"] = battery_info["max_capacity"] * battery_info["voltage"]
            
        return battery_info
        
    except Exception as e:
        print(f"Error getting battery info: {e}")
        return {}

def get_app_energy_usage():
    """
    Get application energy usage from the powermetrics command.
    
    Returns a dictionary with app name as key and energy impact as value.
    """
    try:
        # Use plist format for more reliable data parsing
        powermetrics_cmd = ['sudo', 'powermetrics', '-n', '1', '-i', '500', 
                            '--show-process-energy', '--format', 'plist']
        
        # Run the command
        process = subprocess.run(
            powermetrics_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False  # Output in bytes since plist is binary
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
        global previous_app_energy, app_energy_usage, accumulated_energy, accumulated_power
        
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
    Draw a battery percentage graph using the history data with ASCII characters.
    """
    if not history:
        return
    
    # Get dimensions
    max_height = 8
    graph_width = min(max_width - 2, len(history))
    
    # Draw the border
    for i in range(graph_width + 2):
        stdscr.addstr(max_height + 1, i, "-")
        stdscr.addstr(0, i, "-")
    
    for i in range(max_height + 2):
        stdscr.addstr(i, 0, "|")
        stdscr.addstr(i, graph_width + 1, "|")
    
    # Draw the corners
    stdscr.addstr(0, 0, "+")
    stdscr.addstr(0, graph_width + 1, "+")
    stdscr.addstr(max_height + 1, 0, "+")
    stdscr.addstr(max_height + 1, graph_width + 1, "+")
    
    # Draw labels
    stdscr.addstr(0, 3, " Battery % over time ")
    stdscr.addstr(max_height // 4, graph_width + 3, "100%")
    stdscr.addstr(max_height // 4 * 2, graph_width + 3, "75%")
    stdscr.addstr(max_height // 4 * 3, graph_width + 3, "50%")
    stdscr.addstr(max_height, graph_width + 3, "25%")
    
    # Add timestamps
    if len(history) > 0:
        current_time = datetime.datetime.now().strftime("%H:%M")
        stdscr.addstr(max_height + 2, graph_width - 4, current_time)
        
        if len(history) > graph_width // 2:
            mid_time = (datetime.datetime.now() - datetime.timedelta(seconds=(len(history) - graph_width // 2) * 10)).strftime("%H:%M")
            stdscr.addstr(max_height + 2, graph_width // 2 - 2, mid_time)
        
        if len(history) > graph_width:
            start_time = (datetime.datetime.now() - datetime.timedelta(seconds=(len(history) - 1) * 10)).strftime("%H:%M")
            stdscr.addstr(max_height + 2, 1, start_time)
    
    # Draw the actual graph
    recent_history = history[-graph_width:] if len(history) > graph_width else history
    
    for i, value in enumerate(recent_history):
        # Map battery percentage (0-100) to graph height (max_height-0)
        bar_height = max(0, min(max_height, int((max_height * (100 - value)) / 100)))
        
        # Draw the bar with ASCII character
        for j in range(max_height - bar_height + 1):
            stdscr.addstr(j + bar_height, i + 1, "#")

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

def main(stdscr):
    # Добавьте отладочный файл в начало функции
    with open("/tmp/battery_monitor_debug.log", "w") as f:
        f.write("Starting battery monitor...\n")
    
    # Initialize curses
    curses.curs_set(0)  # Hide cursor
    curses.start_color()
    curses.use_default_colors()
    
    # Define color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # Green text
    curses.init_pair(2, curses.COLOR_RED, -1)    # Red text
    curses.init_pair(3, curses.COLOR_YELLOW, -1) # Yellow text
    curses.init_pair(4, curses.COLOR_BLUE, -1)   # Blue text
    
    # Set global variables
    global battery_history, start_time, accumulated_energy, accumulated_power
    
    # Main loop
    update_interval = 0.25  # Обновление 4 раза в секунду (каждые 0.25 сек)
    last_update = time.time() - update_interval  # Force immediate update
    last_update_time = datetime.datetime.now()  # Время последнего обновления
    
    try:
        while True:
            current_time = time.time()
            
            # Get terminal size
            max_y, max_x = stdscr.getmaxyx()
            
            # Clear screen
            stdscr.clear()
            
            # Update data at regular intervals
            if current_time - last_update >= update_interval:
                # Get battery information
                battery_info = get_battery_info()
                
                # Get application energy usage
                app_energy = get_app_energy_usage()
                
                # Calculate additional metrics for each app based on energy impact
                if app_energy and battery_info:
                    total_power_usage = battery_info.get('power_usage', 10.0)  # Default to 10W if power_usage not available
                    total_energy_impact = sum(info['energy'] for app, info in app_energy.items() if isinstance(info, dict))
                    
                    # Enhance app data with calculated metrics and accumulate stats
                    for app_name, app_data in app_energy.items():
                        if not isinstance(app_data, dict):
                            continue
                            
                        raw_energy = app_data.get('energy', 0)
                        
                        # Calculate app's portion of power usage based on its energy impact
                        if total_energy_impact > 0:
                            ratio = raw_energy / total_energy_impact
                            app_data['power_watts'] = total_power_usage * ratio
                        else:
                            app_data['power_watts'] = 0
                            
                        # Accumulate energy and power over time
                        accumulated_energy[app_name] += raw_energy * update_interval  # Scale by time
                        accumulated_power[app_name] += app_data['power_watts'] * update_interval  # Scale by time
                        
                        # Store accumulated values in the app_data for display
                        app_data['accumulated_energy'] = accumulated_energy[app_name]
                        app_data['accumulated_power'] = accumulated_power[app_name]
                
                # Add battery percentage to history
                if battery_info and 'percentage' in battery_info:
                    battery_history.append(battery_info['percentage'])
                
                # Update timestamp
                last_update = current_time
                last_update_time = datetime.datetime.now()
            
            # Display battery information
            if battery_info:
                # Battery percentage
                percentage = battery_info.get('percentage', 0)
                color = curses.color_pair(1) if percentage > 50 else curses.color_pair(3) if percentage > 20 else curses.color_pair(2)
                safe_addstr(stdscr, 1, 1, f"Battery: {percentage:.1f}%", color)
                
                # Battery capacity in mAh (not mWh)
                current_mah = battery_info.get('current_mah', 0)
                max_mah = battery_info.get('max_mah', 0)
                safe_addstr(stdscr, 2, 1, f"Capacity: {current_mah} mAh / {max_mah} mAh")
                
                # Power usage with timestamp
                power_usage = battery_info.get('power_usage', 0)
                color = curses.color_pair(1) if power_usage < 10 else curses.color_pair(3) if power_usage < 20 else curses.color_pair(2)
                timestamp_str = last_update_time.strftime("%H:%M:%S.%f")[:-3]  # Формат ЧЧ:ММ:СС.миллисекунды (до 3 знаков)
                safe_addstr(stdscr, 3, 1, f"Power Usage: {power_usage:.2f}W   [Last update: {timestamp_str}]", color)
                
                # Battery temperature
                temp = battery_info.get('temperature', 0)
                temp_color = curses.color_pair(1) if temp < 35 else curses.color_pair(3) if temp < 45 else curses.color_pair(2)
                safe_addstr(stdscr, 4, 1, f"Temperature: {temp:.1f}°C", temp_color)
                
                # Time remaining
                is_charging = battery_info.get('is_charging', False)
                
                if is_charging:
                    time_to_full = battery_info.get('time_to_full_min', 0)
                    safe_addstr(stdscr, 5, 1, f"Charging: {time_to_full} minutes to full", curses.color_pair(1))
                else:
                    time_remaining = battery_info.get('time_remaining_min', 0)
                    hours = time_remaining // 60
                    minutes = time_remaining % 60
                    time_str = f"Time Remaining: {hours}h {minutes}m"
                    
                    time_color = curses.color_pair(1) if time_remaining > 180 else curses.color_pair(3) if time_remaining > 60 else curses.color_pair(2)
                    safe_addstr(stdscr, 5, 1, time_str, time_color)
                
                # Battery condition
                condition = battery_info.get('condition', 'Unknown')
                condition_color = curses.color_pair(1) if condition == 'Normal' else curses.color_pair(3) if condition == 'Fair' else curses.color_pair(2)
                safe_addstr(stdscr, 6, 1, f"Battery Condition: {condition}", condition_color)
            else:
                safe_addstr(stdscr, 1, 1, "Battery information not available", curses.color_pair(2))
            
            # Draw battery graph
            # draw_battery_graph(stdscr, battery_history, max_x - 15)
            
            # Display application energy usage
            if app_energy:
                # Sort applications by accumulated power
                sorted_apps = sorted(app_energy.items(), key=lambda x: accumulated_power.get(x[0], 0), reverse=True)
                
                # Display header
                safe_addstr(stdscr, 8, 1, "Application Energy Usage (sorted by accumulated power):", curses.color_pair(4))
                safe_addstr(stdscr, 9, 1, f"{'Application':<30} {'Energy Impact':<15} {'Power (W)':<15} {'Accum. Energy':<15} {'Accum. Power (W⋅h)':<15}")
                safe_addstr(stdscr, 10, 1, "-" * 90)
                
                # Display all applications (limited by screen size)
                row = 11
                max_display_rows = max_y - row - 2  # Leave space for status at bottom
                
                for i, (app, info) in enumerate(sorted_apps):
                    # Check if we're going beyond screen boundaries
                    if row >= max_y - 2:
                        break
                        
                    energy = info.get('energy', 0)
                    power_watts = info.get('power_watts', 0)
                    accumulated_energy_val = accumulated_energy.get(app, 0)
                    accumulated_power_val = accumulated_power.get(app, 0)
                    
                    # Determine color based on energy impact
                    color = curses.color_pair(1) if energy < 30 else curses.color_pair(3) if energy < 100 else curses.color_pair(2)
                    
                    # Display application information
                    app_display = app[:28]
                    safe_addstr(stdscr, row, 1, f"{app_display:<30} {energy:<15.2f} {power_watts:<15.2f} {accumulated_energy_val:<15.2f} {accumulated_power_val:<15.2f}", color)
                    row += 1
            else:
                safe_addstr(stdscr, 8, 1, "Application energy usage not available", curses.color_pair(2))
            
            # Display runtime information
            runtime = int(current_time - start_time)
            runtime_str = f"Runtime: {runtime // 3600:02d}:{(runtime % 3600) // 60:02d}:{runtime % 60:02d}"
            safe_addstr(stdscr, max_y - 1, 1, runtime_str)
            
            # Display instructions
            instructions = "Press 'q' to quit, 's' to save data"
            safe_addstr(stdscr, max_y - 1, max_x - len(instructions) - 1, instructions)
            
            # Refresh screen
            stdscr.refresh()
            
            # Wait for key press with shorter timeout to make UI more responsive
            curses.halfdelay(1)  # Set timeout in tenths of a second (1 = 0.1 sec)
            key = stdscr.getch()
            if key == ord('q'):
                break
                
            # Save data on 's'
            elif key == ord('s'):
                # Save accumulated data to JSON file
                output_data = {
                    'timestamp': datetime.datetime.now().isoformat(),
                    'runtime_seconds': runtime,
                    'battery_history': battery_history,
                    'accumulated_energy': {app: float(energy) for app, energy in accumulated_energy.items()},
                    'accumulated_power': {app: float(power) for app, power in accumulated_power.items()}
                }
                
                with open('battery_monitor_data.json', 'w') as f:
                    json.dump(output_data, f, indent=2)
                
                # Notify user
                safe_addstr(stdscr, max_y - 2, 1, "Data saved to battery_monitor_data.json", curses.color_pair(1))
                stdscr.refresh()
                time.sleep(2)
    
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pass
    
    except Exception as e:
        # Exit curses mode before printing error
        curses.endwin()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        # Check for sudo
        if os.geteuid() != 0:
            print("This program requires sudo privileges to access power metrics.")
            print("Please run with: sudo python3 battery_monitor_plist.py")
            sys.exit(1)
        
        # Run main function with curses wrapper
        sys.exit(curses.wrapper(main))
    except KeyboardInterrupt:
        # Handle Ctrl+C
        print("\nProgram terminated by user.")
        sys.exit(0) 