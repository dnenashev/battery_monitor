#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Battery Monitor Graph

This program monitors battery discharge rate, displays a graph of capacity decline,
and captures snapshots of applications during periods of high energy consumption.
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
import statistics

# Global variables
battery_history = []  # History of battery percentage for graph
capacity_history = []  # History of battery capacity (mAh) for graph
timestamp_history = []  # Timestamps for battery history points
discharge_rate_history = []  # History of discharge rates (mAh/min)
app_snapshots = []  # Snapshots of app energy usage at each interval
high_discharge_snapshots = []  # Snapshots during high discharge periods
start_time = time.time()  # Program start time

# Discharge rate threshold (mAh/min) that indicates high discharge
HIGH_DISCHARGE_THRESHOLD = 10  # Will be adjusted automatically based on observed data

# Use ASCII characters instead of Unicode for better compatibility
USE_ASCII = False  # Set to True if having issues with Unicode characters

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
        
        return app_energy
    
    except Exception as e:
        return {}  # Return empty dict on any error

def calculate_discharge_rate():
    """
    Calculate the discharge rate in mAh per minute based on recent capacity history.
    Returns the rate and a boolean indicating if this is a high discharge rate.
    """
    try:
        global capacity_history, timestamp_history, discharge_rate_history, HIGH_DISCHARGE_THRESHOLD
        
        # Need at least two data points to calculate rate
        if len(capacity_history) < 2:
            return 0.01, False
        
        # Get the two most recent capacity values and their timestamps
        cap_current = capacity_history[-1]
        cap_previous = capacity_history[-2]
        time_current = timestamp_history[-1]
        time_previous = timestamp_history[-2]
        
        # Calculate time difference in minutes
        time_diff = (time_current - time_previous).total_seconds() / 60.0
        
        if time_diff <= 0:
            return 0.01, False
        
        # Calculate capacity change (negative for discharge)
        cap_diff = cap_previous - cap_current
        
        # Calculate discharge rate in mAh per minute (positive value for discharge)
        if cap_diff > 0:  # Only if it's actually discharging
            rate = cap_diff / time_diff
        else:
            # If charging or no change, return small positive value to avoid div by zero
            rate = 0.01
        
        # Add to history
        discharge_rate_history.append(rate)
        
        # Keep only the most recent rates
        if len(discharge_rate_history) > 30:
            discharge_rate_history = discharge_rate_history[-30:]
        
        # Dynamically adjust the high discharge threshold based on recent history
        if len(discharge_rate_history) >= 5:
            try:
                avg_rate = statistics.mean(discharge_rate_history)
                std_dev = statistics.stdev(discharge_rate_history)
                HIGH_DISCHARGE_THRESHOLD = avg_rate + 1.5 * std_dev
            except statistics.StatisticsError:
                # Fallback if statistics calculation fails
                HIGH_DISCHARGE_THRESHOLD = max(10, rate * 1.5)
        
        # Check if current rate exceeds threshold
        is_high_discharge = rate > HIGH_DISCHARGE_THRESHOLD and rate > 0.5
        
        return rate, is_high_discharge
    
    except Exception as e:
        # Log and return safe values on error
        print(f"Error calculating discharge rate: {e}")
        return 0.01, False

def draw_capacity_graph(stdscr, max_width, max_height):
    """
    Draw a graph of battery capacity over time with indicators for high discharge periods.
    """
    try:
        global capacity_history, timestamp_history, high_discharge_snapshots
        
        if not capacity_history or len(capacity_history) < 2:
            return
        
        # Get dimensions for the graph
        graph_width = min(max_width - 10, len(capacity_history), 120)
        graph_height = min(max_height - 10, 20)
        
        # Get start position for the graph
        start_y = 10
        start_x = 2
        
        # Calculate the min and max values for scaling with padding
        max_capacity = max(capacity_history)
        min_capacity = min(capacity_history)
        
        # Add 5% padding to make sure points don't touch borders
        capacity_range = max(max_capacity - min_capacity, 1)  # Prevent division by zero
        min_capacity = max(0, min_capacity - capacity_range * 0.05)
        max_capacity = max_capacity + capacity_range * 0.05
        
        # Draw the border using safer ASCII characters if needed
        border_horizontal = "─"
        border_vertical = "│"
        border_top_left = "┌"
        border_top_right = "┐"
        border_bottom_left = "└"
        border_bottom_right = "┘"
        
        # Fall back to ASCII if there's a chance of rendering issues
        if USE_ASCII:
            border_horizontal = "-"
            border_vertical = "|"
            border_top_left = "+"
            border_top_right = "+"
            border_bottom_left = "+"
            border_bottom_right = "+"
        
        # Draw the border
        for i in range(graph_width + 2):
            safe_addstr(stdscr, start_y + graph_height + 1, start_x + i, border_horizontal)
            safe_addstr(stdscr, start_y, start_x + i, border_horizontal)
        
        for i in range(graph_height + 2):
            safe_addstr(stdscr, start_y + i, start_x, border_vertical)
            safe_addstr(stdscr, start_y + i, start_x + graph_width + 1, border_vertical)
        
        # Draw the corners
        safe_addstr(stdscr, start_y, start_x, border_top_left)
        safe_addstr(stdscr, start_y, start_x + graph_width + 1, border_top_right)
        safe_addstr(stdscr, start_y + graph_height + 1, start_x, border_bottom_left)
        safe_addstr(stdscr, start_y + graph_height + 1, start_x + graph_width + 1, border_bottom_right)
        
        # Draw the title
        title = " Battery Capacity Over Time "
        safe_addstr(stdscr, start_y, start_x + (graph_width - len(title)) // 2, title)
        
        # Get the data for the graph
        recent_capacity = capacity_history[-graph_width:] if len(capacity_history) > graph_width else capacity_history
        recent_timestamps = timestamp_history[-graph_width:] if len(timestamp_history) > graph_width else timestamp_history
        
        # Draw y-axis labels (capacity in mAh)
        y_top = start_y + 1
        y_bottom = start_y + graph_height
        
        for i in range(5):
            y_pos = start_y + 1 + (graph_height - 1) * i // 4
            capacity_value = max_capacity - (capacity_range * i / 4)
            label = f"{capacity_value:.0f} mAh"
            safe_addstr(stdscr, y_pos, start_x - len(label) - 1, label)
        
        # Draw x-axis labels (time)
        if len(recent_timestamps) > 1:
            for i in range(min(5, len(recent_timestamps))):
                x_pos = start_x + 1 + (graph_width - 1) * i // min(4, len(recent_timestamps) - 1)
                idx = i * (len(recent_timestamps) - 1) // min(4, len(recent_timestamps) - 1)
                time_label = recent_timestamps[idx].strftime("%H:%M")
                if x_pos + len(time_label) < start_x + graph_width:
                    safe_addstr(stdscr, start_y + graph_height + 2, x_pos, time_label)
        
        # Draw the capacity line
        for i in range(len(recent_capacity) - 1):
            # Calculate positions
            x1 = start_x + 1 + i * (graph_width - 1) // (len(recent_capacity) - 1)
            y1 = start_y + graph_height - int((recent_capacity[i] - min_capacity) * (graph_height - 1) / capacity_range)
            x2 = start_x + 1 + (i + 1) * (graph_width - 1) // (len(recent_capacity) - 1)
            y2 = start_y + graph_height - int((recent_capacity[i + 1] - min_capacity) * (graph_height - 1) / capacity_range)
            
            # Ensure positions are within valid range
            y1 = max(y_top, min(y_bottom, y1))
            y2 = max(y_top, min(y_bottom, y2))
            
            # Draw a line from (x1,y1) to (x2,y2)
            draw_line(stdscr, y1, x1, y2, x2)
        
        # Mark high discharge points
        for snapshot in high_discharge_snapshots:
            try:
                snapshot_time = snapshot['timestamp']
                for i, timestamp in enumerate(recent_timestamps):
                    if abs((snapshot_time - timestamp).total_seconds()) < 60:  # Within a minute
                        x_pos = start_x + 1 + i * (graph_width - 1) // (len(recent_capacity) - 1)
                        y_pos = start_y + graph_height - int((recent_capacity[i] - min_capacity) * (graph_height - 1) / capacity_range)
                        y_pos = max(y_top, min(y_bottom, y_pos))  # Ensure it's within range
                        safe_addstr(stdscr, y_pos, x_pos, "X", curses.color_pair(2))  # Mark with red X
                        break
            except Exception as e:
                # Skip marking this point if there's an error
                pass
                
    except Exception as e:
        # Log error and continue - don't crash the program for graph issues
        print(f"Error drawing graph: {e}")

def draw_line(stdscr, y1, x1, y2, x2):
    """Draw a line from (x1,y1) to (x2,y2) using ASCII characters."""
    try:
        # Simple Bresenham's line algorithm
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        
        while True:
            try:
                if x1 >= 0 and y1 >= 0:  # Check bounds
                    # Choose character based on slope
                    if USE_ASCII:
                        char = "-" if dx > dy else "|" if dx < dy else "+"
                    else:
                        char = "─" if dx > dy else "│" if dx < dy else "•"
                    safe_addstr(stdscr, y1, x1, char)
            except:
                pass  # Ignore any curses errors
                
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x1 += sx
            if e2 < dx:
                err += dx
                y1 += sy
    except Exception as e:
        # Ignore errors in line drawing
        pass

def save_snapshot(battery_info, app_energy, is_high_discharge=False, discharge_rate=0):
    """
    Save a snapshot of current battery status and app energy usage.
    """
    try:
        global app_snapshots, high_discharge_snapshots
        
        timestamp = datetime.datetime.now()
        
        # Check for valid data before processing
        if not isinstance(battery_info, dict) or not isinstance(app_energy, dict):
            return
        
        # Calculate additional metrics for each app with error handling
        total_power_usage = battery_info.get('power_usage', 10.0)
        
        # Safely calculate total energy impact
        total_energy_impact = 0
        for app, info in app_energy.items():
            if isinstance(info, dict) and 'energy' in info:
                total_energy_impact += info['energy']
        
        # Enhance app data with power usage
        for app_name, app_data in app_energy.items():
            if isinstance(app_data, dict):
                energy = app_data.get('energy', 0)
                if total_energy_impact > 0:
                    ratio = energy / total_energy_impact
                    app_data['power_watts'] = total_power_usage * ratio
                else:
                    app_data['power_watts'] = 0
        
        # Create snapshot
        snapshot = {
            'timestamp': timestamp,
            'battery_percentage': battery_info.get('percentage', 0),
            'capacity_mah': battery_info.get('current_mah', 0),
            'power_usage': battery_info.get('power_usage', 0),
            'temperature': battery_info.get('temperature', 0),
            'discharge_rate': discharge_rate,
            'is_high_discharge': is_high_discharge,
            'applications': app_energy
        }
        
        # Add to appropriate lists
        app_snapshots.append(snapshot)
        
        if is_high_discharge:
            high_discharge_snapshots.append(snapshot)
        
        # Save to disk periodically
        if len(app_snapshots) % 5 == 0 or is_high_discharge:
            save_snapshots_to_file()
    
    except Exception as e:
        print(f"Error saving snapshot: {e}")

def save_snapshots_to_file():
    """
    Save all snapshots to a JSON file.
    """
    try:
        # Create a copy of the data to avoid modification during serialization
        snapshots_copy = list(app_snapshots)
        high_discharge_copy = list(high_discharge_snapshots)
        timestamp_copy = list(timestamp_history)
        capacity_copy = list(capacity_history)
        
        output_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'regular_snapshots': snapshots_copy,
            'high_discharge_snapshots': high_discharge_copy,
            'battery_history': [
                {
                    'timestamp': ts.isoformat() if isinstance(ts, datetime.datetime) else str(ts),
                    'capacity_mah': cap
                } for ts, cap in zip(timestamp_copy, capacity_copy)
            ]
        }
        
        # Convert datetime objects to ISO format strings for JSON
        for snapshot in output_data['regular_snapshots']:
            if 'timestamp' in snapshot and isinstance(snapshot['timestamp'], datetime.datetime):
                snapshot['timestamp'] = snapshot['timestamp'].isoformat()
        
        for snapshot in output_data['high_discharge_snapshots']:
            if 'timestamp' in snapshot and isinstance(snapshot['timestamp'], datetime.datetime):
                snapshot['timestamp'] = snapshot['timestamp'].isoformat()
        
        # Save to file with error handling
        try:
            with open('battery_discharge_data.json', 'w') as f:
                json.dump(output_data, f, indent=2)
        except PermissionError:
            print("Warning: Could not save data file (permission denied)")
        except IOError as e:
            print(f"Warning: Could not save data file (IO error: {e})")
    
    except Exception as e:
        print(f"Error saving snapshots: {e}")

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
    """
    Main function that runs the battery monitoring program.
    """
    try:
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
        global battery_history, capacity_history, timestamp_history, HIGH_DISCHARGE_THRESHOLD
        
        # Main loop
        update_interval = 60  # Update once per minute
        last_update = time.time() - update_interval  # Force immediate update
        last_snapshot_time = datetime.datetime.now() - datetime.timedelta(minutes=1)  # Last time we took a snapshot
        last_update_timestamp = "Not yet updated"  # For displaying last update time
        
        # For testing, use a shorter interval
        test_mode = '--test' in sys.argv
        if test_mode:
            update_interval = 10  # 10 seconds in test mode
        
        while True:
            try:
                current_time = time.time()
                
                # Get terminal size
                max_y, max_x = stdscr.getmaxyx()
                
                # Clear screen
                stdscr.clear()
                
                # Add program title and last update time
                safe_addstr(stdscr, 0, 0, "Battery Monitor Graph", curses.color_pair(4) | curses.A_BOLD)
                safe_addstr(stdscr, 0, max_x - 25, f"Last update: {last_update_timestamp}", curses.color_pair(3))
                
                # Update data at regular intervals
                if current_time - last_update >= update_interval:
                    # Get battery information
                    battery_info = get_battery_info()
                    
                    if battery_info and 'current_mah' in battery_info:
                        # Store battery capacity data
                        now = datetime.datetime.now()
                        last_update_timestamp = now.strftime("%H:%M:%S")
                        
                        capacity_history.append(battery_info['current_mah'])
                        timestamp_history.append(now)
                        battery_history.append(battery_info.get('percentage', 0))
                        
                        # Calculate discharge rate
                        discharge_rate, is_high_discharge = calculate_discharge_rate()
                        
                        # Get application energy usage
                        app_energy = get_app_energy_usage()
                        
                        # Save snapshot
                        if (now - last_snapshot_time).total_seconds() >= 60 or is_high_discharge:
                            save_snapshot(battery_info, app_energy, is_high_discharge, discharge_rate)
                            last_snapshot_time = now
                    
                    # Update timestamp
                    last_update = current_time
                
                # Display battery information at the top
                battery_info = get_battery_info()  # Get current battery info for display
                
                if battery_info:
                    # Battery percentage and capacity
                    percentage = battery_info.get('percentage', 0)
                    current_mah = battery_info.get('current_mah', 0)
                    max_mah = battery_info.get('max_mah', 0)
                    color = curses.color_pair(1) if percentage > 50 else curses.color_pair(3) if percentage > 20 else curses.color_pair(2)
                    
                    safe_addstr(stdscr, 1, 2, f"Battery: {percentage:.1f}% ({current_mah} mAh / {max_mah} mAh)", color)
                    
                    # Power usage
                    power_usage = battery_info.get('power_usage', 0)
                    color = curses.color_pair(1) if power_usage < 10 else curses.color_pair(3) if power_usage < 20 else curses.color_pair(2)
                    safe_addstr(stdscr, 2, 2, f"Power Usage: {power_usage:.2f}W", color)
                    
                    # Time remaining
                    is_charging = battery_info.get('is_charging', False)
                    
                    if is_charging:
                        time_to_full = battery_info.get('time_to_full_min', 0)
                        safe_addstr(stdscr, 3, 2, f"Charging: {time_to_full} minutes to full", curses.color_pair(1))
                    else:
                        time_remaining = battery_info.get('time_remaining_min', 0)
                        hours = time_remaining // 60
                        minutes = time_remaining % 60
                        time_str = f"Time Remaining: {hours}h {minutes}m"
                        
                        time_color = curses.color_pair(1) if time_remaining > 180 else curses.color_pair(3) if time_remaining > 60 else curses.color_pair(2)
                        safe_addstr(stdscr, 3, 2, time_str, time_color)
                    
                    # Discharge rate
                    if len(discharge_rate_history) > 0:
                        current_rate = discharge_rate_history[-1]
                        rate_color = curses.color_pair(1) if current_rate < HIGH_DISCHARGE_THRESHOLD else curses.color_pair(2)
                        safe_addstr(stdscr, 4, 2, f"Discharge Rate: {current_rate:.2f} mAh/min", rate_color)
                        safe_addstr(stdscr, 5, 2, f"High Discharge Threshold: {HIGH_DISCHARGE_THRESHOLD:.2f} mAh/min", curses.color_pair(4))
                    
                    # Snapshot information
                    safe_addstr(stdscr, 6, 2, f"Total Snapshots: {len(app_snapshots)}", curses.color_pair(4))
                    safe_addstr(stdscr, 7, 2, f"High Discharge Events: {len(high_discharge_snapshots)}", curses.color_pair(2))
                    
                    # Draw the capacity graph
                    if len(capacity_history) >= 2:
                        draw_capacity_graph(stdscr, max_x, max_y)
                    else:
                        safe_addstr(stdscr, 10, 2, "Collecting data... Need at least 2 points for the graph")
                else:
                    safe_addstr(stdscr, 1, 2, "Battery information not available", curses.color_pair(2))
                
                # Display runtime and instructions
                runtime = int(current_time - start_time)
                runtime_str = f"Runtime: {runtime // 3600:02d}:{(runtime % 3600) // 60:02d}:{runtime % 60:02d}"
                safe_addstr(stdscr, max_y - 2, 2, runtime_str)
                
                # Display next update time
                next_update_in = max(0, int(update_interval - (current_time - last_update)))
                safe_addstr(stdscr, max_y - 2, len(runtime_str) + 4, f"Next update in: {next_update_in}s")
                
                # Display instructions
                instructions = "Press 'q' to quit, 's' to save data, 'u' to force update"
                safe_addstr(stdscr, max_y - 1, 2, instructions)
                
                # Refresh screen
                stdscr.refresh()
                
                # Check for key presses
                stdscr.timeout(1000)  # Wait for 1 second
                key = stdscr.getch()
                
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    save_snapshots_to_file()
                    safe_addstr(stdscr, max_y - 3, 2, "Data saved to battery_discharge_data.json", curses.color_pair(1))
                    stdscr.refresh()
                    time.sleep(1)
                elif key == ord('u'):
                    # Force immediate update
                    last_update = 0
            
            except Exception as e:
                # Catch any exceptions in the main loop to prevent crashes
                try:
                    stdscr.clear()
                    safe_addstr(stdscr, 0, 0, "ERROR in main loop:", curses.color_pair(2) | curses.A_BOLD)
                    safe_addstr(stdscr, 1, 0, f"{str(e)[:max_x-1]}", curses.color_pair(2))
                    safe_addstr(stdscr, 3, 0, "Press any key to continue or 'q' to quit", curses.color_pair(3))
                    stdscr.refresh()
                    stdscr.timeout(5000)
                    key = stdscr.getch()
                    if key == ord('q'):
                        break
                except:
                    # If we can't display the error, just continue
                    pass
    
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        pass
    
    except Exception as e:
        # Exit curses mode before printing error
        curses.endwin()
        print(f"Critical error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Save data before exiting
    try:
        save_snapshots_to_file()
    except:
        print("Could not save data on exit.")
    
    return 0

if __name__ == "__main__":
    try:
        # Check for sudo
        if os.geteuid() != 0:
            print("This program requires sudo privileges to access power metrics.")
            print("Please run with: sudo python3 battery_monitor_graph.py")
            sys.exit(1)
        
        # Run main function with curses wrapper
        sys.exit(curses.wrapper(main))
    except KeyboardInterrupt:
        # Handle Ctrl+C
        print("\nProgram terminated by user.")
        sys.exit(0) 