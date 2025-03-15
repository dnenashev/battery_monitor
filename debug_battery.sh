#!/bin/bash
python3 -u battery_monitor_graph.py --test 2>&1 | tee /tmp/battery_output.log
