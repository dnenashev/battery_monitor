#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Battery Monitor Graph (Debug Version)

This program monitors battery discharge rate with enhanced error handling.
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
import traceback
import logging

# Setup logging
logging.basicConfig(
    filename="/tmp/battery_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

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

# Use ASCII instead of Unicode for better compatibility
USE_ASCII = True

def get_battery_info():
    """
    Get battery information directly from macOS system using IORegistry.
    """
    try:
        logging.debug("Getting battery info")
        # Initialize the battery info dictionary
        battery_info = {}
        
        # Use ioreg to get battery information
        ioreg_output = subprocess.run(['ioreg', '-r', '-c', 'AppleSmartBattery'], capture_output=True, text=True)
        ioreg_text = ioreg_output.stdout
        
        # Extract design capacity (from factory) in mAh
        design_capacity_match = re.search(r'"DesignCapacity" = (\d+)', ioreg_text)
        if design_capacity_match:
            design_capacity = int(design_capacity_match.group(1))
            battery_info["design_capacity"] = design_capacity
            logging.debug(f"Design capacity: {design_capacity} mAh")
        else:
            # If design capacity not found, use a typical MacBook value
            design_capacity = 5000
            battery_info["design_capacity"] = design_capacity
            logging.debug("Design capacity not found, using default 5000 mAh")
        
        # Extract relative capacity values
        max_capacity_match = re.search(r'"MaxCapacity" = (\d+)', ioreg_text)
        current_capacity_match = re.search(r'"CurrentCapacity" = (\d+)', ioreg_text)
        
        if max_capacity_match and current_capacity_match:
            relative_max = int(max_capacity_match.group(1))
            relative_current = int(current_capacity_match.group(1))
            
            logging.debug(f"Relative max capacity: {relative_max}")
            logging.debug(f"Relative current capacity: {relative_current}")
            
            # Convert relative values to absolute mAh using design capacity
            # In macOS, MaxCapacity is often a percentage of design capacity
            max_capacity = int(design_capacity * relative_max / 100.0)
            
            # Current capacity is proportional to max capacity
            if relative_max > 0:
                current_capacity = int(max_capacity * relative_current / relative_max)
            else:
                current_capacity = 0
            
            battery_info["max_capacity"] = max_capacity
            battery_info["current_capacity"] = current_capacity
            
            # Calculate percentage directly
            if max_capacity > 0:
                battery_info["percentage"] = (current_capacity / max_capacity) * 100
            
            # Set values for compatibility
            battery_info["current_mah"] = current_capacity
            battery_info["max_mah"] = max_capacity
            
            logging.debug(f"Calculated max capacity: {max_capacity} mAh")
            logging.debug(f"Calculated current capacity: {current_capacity} mAh")
            logging.debug(f"Battery percentage: {battery_info.get('percentage', 0):.1f}%")
            
            # Extract power source
            external_connected_match = re.search(r'"ExternalConnected" = ([a-zA-Z]+)', ioreg_text)
            if external_connected_match:
                is_external_connected = external_connected_match.group(1).lower() == "yes"
                battery_info["is_charging"] = is_external_connected
                logging.debug(f"Power source: {'AC' if is_external_connected else 'Battery'}")
            
            # Extract current (amperage)
            amperage_match = re.search(r'"InstantAmperage" = (-?\d+)', ioreg_text)
            if amperage_match:
                amperage = int(amperage_match.group(1))
                # Convert to Amps - may need adjustment based on actual values
                current = amperage / 1000.0
                battery_info["current"] = current
                logging.debug(f"Current: {current:.3f} A")
        
        logging.debug(f"Battery info retrieved: {battery_info}")
        return battery_info
        
    except Exception as e:
        logging.error(f"Error getting battery info: {e}")
        logging.error(traceback.format_exc())
        # Return default values if there's an error
        return {"percentage": 100, "current_mah": 5000, "max_mah": 5000, "is_charging": False}

def get_app_energy_usage():
    """
    Get application energy usage from the powermetrics command.
    """
    try:
        logging.debug("Getting app energy usage")
        # For debugging, return a simple dict
        return {
            "App1": {"energy": 50, "pid": 1234},
            "App2": {"energy": 30, "pid": 5678},
            "App3": {"energy": 20, "pid": 9012}
        }
    
    except Exception as e:
        logging.error(f"Error getting app energy: {e}")
        logging.error(traceback.format_exc())
        return {}  # Return empty dict on any error

def calculate_discharge_rate():
    """
    Calculate the discharge rate in mAh per minute.
    """
    try:
        logging.debug("Calculating discharge rate")
        global capacity_history, timestamp_history, discharge_rate_history, HIGH_DISCHARGE_THRESHOLD
        
        # Need at least two data points to calculate rate
        if len(capacity_history) < 2:
            logging.debug("Not enough data points for discharge rate")
            return 0, False
        
        # Get the two most recent capacity values and their timestamps
        cap_current = capacity_history[-1]
        cap_previous = capacity_history[-2]
        time_current = timestamp_history[-1]
        time_previous = timestamp_history[-2]
        
        # Calculate time difference in minutes
        time_diff = (time_current - time_previous).total_seconds() / 60.0
        
        if time_diff <= 0:
            logging.debug("Invalid time difference")
            return 0, False
        
        # Calculate capacity change (negative for discharge)
        cap_diff = cap_previous - cap_current
        
        # Log the capacity difference
        logging.debug(f"Capacity difference: {cap_diff} mAh over {time_diff:.2f} minutes")
        
        # Calculate discharge rate in mAh per minute (positive value for discharge)
        if cap_diff > 0:  # Only if it's actually discharging
            rate = cap_diff / time_diff
        else:
            # If charging or no change, report a very small positive number instead of zero
            # This helps prevent division by zero issues later
            rate = 0.01
        
        # Add to history
        discharge_rate_history.append(rate)
        
        # Keep only the most recent rates
        if len(discharge_rate_history) > 30:
            discharge_rate_history = discharge_rate_history[-30:]
        
        # Calculate average discharge rate
        avg_rate = sum(discharge_rate_history) / len(discharge_rate_history)
        
        # Adjust threshold based on average
        if len(discharge_rate_history) >= 5:
            try:
                std_dev = statistics.stdev(discharge_rate_history)
                HIGH_DISCHARGE_THRESHOLD = avg_rate + 1.5 * std_dev
            except statistics.StatisticsError:
                # Fallback if statistics calculation fails
                HIGH_DISCHARGE_THRESHOLD = avg_rate * 1.5
        
        # Check if current rate exceeds threshold
        is_high_discharge = rate > HIGH_DISCHARGE_THRESHOLD and rate > 0.5
        
        logging.debug(f"Discharge rate: {rate:.2f} mAh/min (avg: {avg_rate:.2f}, threshold: {HIGH_DISCHARGE_THRESHOLD:.2f})")
        logging.debug(f"High discharge: {is_high_discharge}")
        
        return rate, is_high_discharge
        
    except Exception as e:
        logging.error(f"Error calculating discharge rate: {e}")
        logging.error(traceback.format_exc())
        return 0.01, False  # Return small non-zero value to prevent div by zero

def draw_simple_graph(stdscr, max_width, max_height):
    """
    Draw a simplified graph of battery capacity over time.
    """
    try:
        logging.debug("Drawing simplified graph")
        global capacity_history, timestamp_history
        
        if not capacity_history or len(capacity_history) < 2:
            logging.debug("Not enough data for graph")
            safe_addstr(stdscr, 10, 2, "Collecting data... Need at least 2 points for the graph")
            return
        
        # Get dimensions for the graph
        graph_width = min(max_width - 10, len(capacity_history), 60)
        graph_height = 10
        
        # Get start position for the graph
        start_y = 10
        start_x = 2
        
        # Log capacity history for debugging
        logging.debug(f"Capacity history (last 5): {capacity_history[-5:] if len(capacity_history) >= 5 else capacity_history}")
        
        # Calculate the min and max values for scaling with padding
        max_capacity = max(capacity_history)
        min_capacity = min(capacity_history)
        
        # Add 10% padding to make sure points don't touch the borders
        capacity_range = max(max_capacity - min_capacity, 1)  # Prevent division by zero
        min_capacity = max(0, min_capacity - capacity_range * 0.1)
        max_capacity = max_capacity + capacity_range * 0.1
        
        logging.debug(f"Graph range: {min_capacity:.1f} to {max_capacity:.1f} mAh")
        
        # Draw a simple ASCII border
        for i in range(graph_width + 2):
            stdscr.addstr(start_y + graph_height + 1, start_x + i, "-")
            stdscr.addstr(start_y, start_x + i, "-")
        
        for i in range(graph_height + 2):
            stdscr.addstr(start_y + i, start_x, "|")
            stdscr.addstr(start_y + i, start_x + graph_width + 1, "|")
        
        # Draw the corners
        stdscr.addstr(start_y, start_x, "+")
        stdscr.addstr(start_y, start_x + graph_width + 1, "+")
        stdscr.addstr(start_y + graph_height + 1, start_x, "+")
        stdscr.addstr(start_y + graph_height + 1, start_x + graph_width + 1, "+")
        
        # Draw the title
        title = " Battery Capacity Over Time "
        stdscr.addstr(start_y, start_x + (graph_width - len(title)) // 2, title)
        
        # Get the data for the graph
        recent_capacity = capacity_history[-graph_width:] if len(capacity_history) > graph_width else capacity_history
        
        # Draw y-axis labels (capacity in mAh) - show at least min and max
        y_top = start_y + 1
        y_bottom = start_y + graph_height
        
        # Draw min capacity label
        min_label = f"{min_capacity:.0f} mAh"
        safe_addstr(stdscr, y_bottom, start_x - len(min_label) - 1, min_label)
        
        # Draw max capacity label
        max_label = f"{max_capacity:.0f} mAh"
        safe_addstr(stdscr, y_top, start_x - len(max_label) - 1, max_label)
        
        # Draw middle capacity label
        mid_capacity = (min_capacity + max_capacity) / 2
        mid_label = f"{mid_capacity:.0f} mAh"
        safe_addstr(stdscr, (y_top + y_bottom) // 2, start_x - len(mid_label) - 1, mid_label)
        
        # Calculate new capacity range after possible adjustments
        capacity_range = max_capacity - min_capacity
        
        # Draw simple points in the graph with improved visibility
        for i, cap in enumerate(recent_capacity):
            x_pos = start_x + 1 + i
            
            # Make sure we're within graph boundaries
            if x_pos < start_x + graph_width + 1:
                # Calculate position, ensuring it's within the graph area
                y_pos = y_bottom - int((cap - min_capacity) * (graph_height - 1) / capacity_range)
                y_pos = max(y_top, min(y_bottom, y_pos))
                
                # Use different characters for better visibility
                point_char = "*"  # Use asterisk for data points
                
                # Draw the point
                stdscr.addstr(y_pos, x_pos, point_char, curses.color_pair(3))  # Yellow for better visibility
        
        # If we have enough data points, try to draw connecting lines
        if len(recent_capacity) >= 2:
            # For each pair of consecutive points
            for i in range(len(recent_capacity) - 1):
                x1 = start_x + 1 + i
                x2 = start_x + 1 + i + 1
                
                # Make sure we're within graph boundaries
                if x2 < start_x + graph_width + 1:
                    # Calculate y positions
                    y1 = y_bottom - int((recent_capacity[i] - min_capacity) * (graph_height - 1) / capacity_range)
                    y2 = y_bottom - int((recent_capacity[i+1] - min_capacity) * (graph_height - 1) / capacity_range)
                    
                    # Ensure positions are within the graph
                    y1 = max(y_top, min(y_bottom, y1))
                    y2 = max(y_top, min(y_bottom, y2))
                    
                    # For simple connecting line, draw a '-' if horizontal, '|' if vertical
                    if y1 == y2:
                        stdscr.addstr(y1, x1, "-", curses.color_pair(4))  # Blue for connecting lines
                    elif x1 == x2:
                        # Draw vertical line segments between points
                        for y in range(min(y1, y2), max(y1, y2) + 1):
                            stdscr.addstr(y, x1, "|", curses.color_pair(4))
        
        logging.debug("Graph drawn successfully")
        
    except Exception as e:
        logging.error(f"Error drawing graph: {e}")
        logging.error(traceback.format_exc())

def save_snapshot(battery_info, app_energy, is_high_discharge=False, discharge_rate=0):
    """
    Save a snapshot of current battery status and app energy usage.
    """
    try:
        logging.debug("Saving snapshot")
        global app_snapshots, high_discharge_snapshots
        
        timestamp = datetime.datetime.now()
        
        # Create snapshot
        snapshot = {
            'timestamp': timestamp,
            'battery_percentage': battery_info.get('percentage', 0),
            'capacity_mah': battery_info.get('current_mah', 0),
            'discharge_rate': discharge_rate,
            'is_high_discharge': is_high_discharge,
            'applications': app_energy
        }
        
        # Add to appropriate lists
        app_snapshots.append(snapshot)
        
        if is_high_discharge:
            high_discharge_snapshots.append(snapshot)
        
        logging.debug(f"Snapshot saved, total: {len(app_snapshots)}")
        
    except Exception as e:
        logging.error(f"Error saving snapshot: {e}")
        logging.error(traceback.format_exc())

def safe_addstr(window, y, x, string, attr=0):
    """
    Safely add a string to a curses window.
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
    except Exception as e:
        # Just ignore any curses errors
        pass

def main(stdscr):
    """
    Main function that runs the battery monitoring program.
    """
    try:
        # Log start of main function
        logging.debug("Starting main function")
        
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
        global battery_history, capacity_history, timestamp_history
        
        # Main loop
        update_interval = 30  # Default: Update every 30 seconds
        last_update = time.time() - update_interval  # Force immediate update
        
        # For testing, use a shorter interval
        test_mode = '--test' in sys.argv
        if test_mode:
            update_interval = 5  # 5 seconds in test mode
            logging.debug("Test mode active, update interval: 5s")
        
        # Last successful update time for display
        last_update_time = "Not yet updated"
        
        while True:
            try:
                current_time = time.time()
                
                # Get terminal size
                max_y, max_x = stdscr.getmaxyx()
                
                # Clear screen
                stdscr.clear()
                
                # Display header
                safe_addstr(stdscr, 0, 0, "Battery Monitor (Debug Version)", curses.color_pair(4) | curses.A_BOLD)
                safe_addstr(stdscr, 0, max_x - 25, f"Last update: {last_update_time}", curses.color_pair(3))
                
                # Update data at regular intervals
                if current_time - last_update >= update_interval:
                    logging.debug("Time to update data")
                    
                    # Get battery information
                    battery_info = get_battery_info()
                    
                    if battery_info and 'current_mah' in battery_info:
                        # Store battery capacity data
                        now = datetime.datetime.now()
                        last_update_time = now.strftime("%H:%M:%S")
                        
                        capacity_history.append(battery_info['current_mah'])
                        timestamp_history.append(now)
                        battery_history.append(battery_info.get('percentage', 0))
                        
                        logging.debug(f"Added capacity point: {battery_info['current_mah']} mAh at {last_update_time}")
                        
                        # Calculate discharge rate
                        discharge_rate, is_high_discharge = calculate_discharge_rate()
                        
                        # Get application energy usage
                        app_energy = get_app_energy_usage()
                        
                        # Save snapshot
                        save_snapshot(battery_info, app_energy, is_high_discharge, discharge_rate)
                        
                        # Update timestamp
                        last_update = current_time
                        logging.debug("Data update completed")
                
                # Display battery information at the top
                battery_info = get_battery_info()
                
                if battery_info:
                    # Battery percentage and capacity
                    percentage = battery_info.get('percentage', 0)
                    current_mah = battery_info.get('current_mah', 0)
                    max_mah = battery_info.get('max_mah', 0)
                    color = curses.color_pair(1) if percentage > 50 else curses.color_pair(3) if percentage > 20 else curses.color_pair(2)
                    
                    safe_addstr(stdscr, 2, 2, f"Battery: {percentage:.1f}% ({current_mah} mAh / {max_mah} mAh)", color)
                    
                    # Add design capacity if available
                    if "design_capacity" in battery_info:
                        design_cap = battery_info["design_capacity"]
                        health = (max_mah / design_cap) * 100 if design_cap > 0 else 0
                        safe_addstr(stdscr, 2, 50, f"Battery Health: {health:.1f}% (Design: {design_cap} mAh)", 
                                   curses.color_pair(1) if health > 80 else curses.color_pair(3) if health > 60 else curses.color_pair(2))
                    
                    # Charging status
                    is_charging = battery_info.get('is_charging', False)
                    status = "Charging" if is_charging else "Discharging"
                    safe_addstr(stdscr, 3, 2, f"Status: {status}", curses.color_pair(1) if is_charging else curses.color_pair(3))
                    
                    # Current (if available)
                    if "current" in battery_info:
                        current_amps = battery_info["current"]
                        safe_addstr(stdscr, 3, 30, f"Current: {abs(current_amps):.3f}A ({'charging' if current_amps > 0 else 'discharging'})",
                                   curses.color_pair(1) if current_amps > 0 else curses.color_pair(3))
                    
                    # Discharge rate
                    if len(discharge_rate_history) > 0:
                        current_rate = discharge_rate_history[-1]
                        avg_rate = sum(discharge_rate_history) / len(discharge_rate_history)
                        rate_color = curses.color_pair(1) if current_rate < HIGH_DISCHARGE_THRESHOLD else curses.color_pair(2)
                        
                        # Show both current and average discharge rates
                        safe_addstr(stdscr, 4, 2, f"Discharge Rate: {current_rate:.2f} mAh/min (avg: {avg_rate:.2f})", rate_color)
                        
                        # Show estimated time remaining based on current capacity and discharge rate
                        if current_rate > 0 and current_mah > 0:
                            remaining_mins = current_mah / current_rate
                            hours = int(remaining_mins / 60)
                            mins = int(remaining_mins % 60)
                            safe_addstr(stdscr, 4, 50, f"Est. Time Remaining: {hours}h {mins}m", 
                                       curses.color_pair(1) if remaining_mins > 180 else curses.color_pair(3) if remaining_mins > 60 else curses.color_pair(2))
                    
                    # Data points and runtime
                    runtime = int(time.time() - start_time)
                    runtime_str = f"{runtime // 3600:02d}:{(runtime % 3600) // 60:02d}:{runtime % 60:02d}"
                    safe_addstr(stdscr, 5, 2, f"Data Points: {len(capacity_history)} (Runtime: {runtime_str})", curses.color_pair(4))
                    safe_addstr(stdscr, 6, 2, f"Snapshots: {len(app_snapshots)}", curses.color_pair(4))
                    
                    # Draw graph only if we have data points
                    if len(capacity_history) >= 2:
                        draw_simple_graph(stdscr, max_x, max_y)
                    else:
                        safe_addstr(stdscr, 10, 2, "Waiting for data... (First update in progress)")
                else:
                    safe_addstr(stdscr, 2, 2, "Battery information not available", curses.color_pair(2))
                
                # Display next update time
                next_update_in = max(0, int(update_interval - (current_time - last_update)))
                safe_addstr(stdscr, max_y - 2, 2, f"Next update in: {next_update_in}s (interval: {update_interval}s)")
                
                # Display instructions
                instructions = "Press 'q' to quit, 'u' to force update, '+/-' to change update interval"
                safe_addstr(stdscr, max_y - 1, 2, instructions)
                
                # Refresh screen
                stdscr.refresh()
                
                # Check for key presses (with shorter timeout)
                stdscr.timeout(500)  # Wait for 0.5 seconds
                key = stdscr.getch()
                
                if key == ord('q'):
                    logging.debug("User pressed 'q', exiting")
                    break
                elif key == ord('u'):
                    # Force immediate update
                    last_update = 0
                    logging.debug("User requested immediate update")
                elif key == ord('+') or key == ord('='):
                    # Increase update interval
                    update_interval = min(update_interval + 5, 300)
                    logging.debug(f"Increased update interval to {update_interval}s")
                elif key == ord('-') or key == ord('_'):
                    # Decrease update interval
                    update_interval = max(update_interval - 5, 5)
                    logging.debug(f"Decreased update interval to {update_interval}s")
                
            except Exception as e:
                # Log any exception in the main loop
                logging.error(f"Exception in main loop: {e}")
                logging.error(traceback.format_exc())
                
                # Try to display error on screen
                try:
                    stdscr.clear()
                    safe_addstr(stdscr, 0, 0, "ERROR: Exception occurred", curses.color_pair(2) | curses.A_BOLD)
                    safe_addstr(stdscr, 1, 0, f"{str(e)[:max_x-1]}", curses.color_pair(2))
                    safe_addstr(stdscr, 3, 0, "Press any key to continue or 'q' to quit", curses.color_pair(3))
                    stdscr.refresh()
                    
                    # Wait for key press
                    stdscr.timeout(5000)  # 5 second timeout
                    key = stdscr.getch()
                    if key == ord('q'):
                        break
                except:
                    # If we can't even display the error, just break
                    break
                
                # Continue with next iteration
                continue
    
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt detected")
        pass
    
    except Exception as e:
        # Exit curses mode before printing error
        curses.endwin()
        logging.error(f"Fatal error in main function: {e}")
        logging.error(traceback.format_exc())
        print(f"Error: {e}")
        return 1
    
    logging.debug("Main function completed successfully")
    return 0

if __name__ == "__main__":
    try:
        logging.info("=== Program started ===")
        
        # Check for sudo
        if os.geteuid() != 0:
            logging.error("Program not run with sudo")
            print("This program requires sudo privileges to access power metrics.")
            print("Please run with: sudo python3 battery_monitor_graph_debug.py")
            sys.exit(1)
        
        # Run main function with curses wrapper
        exit_code = curses.wrapper(main)
        logging.info(f"Program exited with code {exit_code}")
        sys.exit(exit_code)
        
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}")
        logging.critical(traceback.format_exc())
        print(f"Critical error: {e}")
        print("Check /tmp/battery_debug.log for details")
        sys.exit(1) 