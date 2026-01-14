from rtde_receive import RTDEReceiveInterface as RTDEReceive
import time
import argparse
import sys
from datetime import datetime
import os

# RuntimeState enum values
RUNTIME_STATE_STOPPING = 0
RUNTIME_STATE_STOPPED = 1
RUNTIME_STATE_PLAYING = 2
RUNTIME_STATE_PAUSING = 3
RUNTIME_STATE_PAUSED = 4
RUNTIME_STATE_RESUMING = 5


def parse_args(args):
    """Parse command line parameters

    Args:
      args ([str]): command line parameters as list of strings

    Returns:
      :obj:`argparse.Namespace`: command line parameters namespace
    """
    parser = argparse.ArgumentParser(
        description="Record data example")
    parser.add_argument(
        "-ip",
        "--robot_ip",
        dest="ip",
        help="IP address of the UR robot",
        type=str,
        default='localhost',
        metavar="<IP address of the UR robot>")
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        help="data output (.csv) file to write to (default is \"robot_data.csv\"",
        type=str,
        default="robot_data.csv",
        metavar="<data output file>")
    parser.add_argument(
        "-f",
        "--frequency",
        dest="frequency",
        help="the frequency at which the data is recorded (default is 500Hz)",
        type=float,
        default=250.0,
        metavar="<frequency>")
    parser.add_argument(
        "-v",
        "--variables",
        dest="variables",
        help="comma-separated list of variables to record (e.g., 'timestamp,target_q,actual_q'). "
             "If not specified, variables are loaded from 'record_variables_input.txt' if it exists, "
             "otherwise all available variables are recorded. "
             "Common variables: timestamp, target_q, target_qd, actual_q, actual_qd, "
             "actual_TCP_pose, actual_TCP_force, etc. See UR RTDE documentation for full list.",
        type=str,
        default=None,
        metavar="<variables>")
    parser.add_argument(
        "--max-file-size",
        dest="max_file_size",
        help="Maximum file size in MB before splitting to a new file (default: no limit). "
             "Useful for keeping files under Excel's 1,048,576 row limit (~70 min at 250Hz).",
        type=float,
        default=None,
        metavar="<MB>")
    parser.add_argument(
        "--max-duration",
        dest="max_duration",
        help="Maximum recording duration in minutes before splitting to a new file (default: no limit). "
             "Example: --max-duration 30 will create a new file every 30 minutes.",
        type=float,
        default=60,
        metavar="<minutes>")

    return parser.parse_args(args)


def load_variables_from_file(filename="record_variables_input.txt"):
    """Load variables from a text file.
    
    The file can contain variables in one of two formats:
    1. One variable per line
    2. Comma-separated on one or multiple lines
    
    Args:
        filename (str): Path to the variables file
        
    Returns:
        list: List of variable names, or empty list if file doesn't exist or is empty
    """
    variables = []
    
    if not os.path.exists(filename):
        return variables
    
    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments (lines starting with #)
                if not line or line.startswith('#'):
                    continue
                
                # Handle comma-separated variables on a line
                if ',' in line:
                    variables.extend([v.strip() for v in line.split(',') if v.strip()])
                else:
                    # Single variable per line
                    variables.append(line)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variables = []
        for v in variables:
            if v not in seen:
                seen.add(v)
                unique_variables.append(v)
        
        return unique_variables
    except Exception as e:
        print(f"Warning: Could not read variables from {filename}: {e}")
        return []


def add_timestamp_to_filename(filename, file_number=None, base_timestamp=None):
    """Add timestamp to filename before the extension.
    
    Args:
        filename (str): Original filename (e.g., "robot_data.csv")
        file_number (int, optional): File number for splitting (e.g., 001, 002)
        base_timestamp (str, optional): Base timestamp to use (for consistent naming across splits)
        
    Returns:
        str: Filename with timestamp (e.g., "robot_data_2024-01-15_14-30-45.csv" or 
             "robot_data_2024-01-15_14-30-45_001.csv")
    """
    # Split filename into name and extension
    name, ext = os.path.splitext(filename)
    
    # Generate or use provided timestamp in format: YYYY-MM-DD_HH-MM-SS
    if base_timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    else:
        timestamp = base_timestamp
    
    # Add file number if provided
    if file_number is not None:
        return f"{name}_{timestamp}_{file_number:03d}{ext}"
    else:
        return f"{name}_{timestamp}{ext}"


def get_file_size_mb(filepath):
    """Get file size in megabytes.
    
    Args:
        filepath (str): Path to the file
        
    Returns:
        float: File size in MB, or 0 if file doesn't exist
    """
    if os.path.exists(filepath):
        return os.path.getsize(filepath) / (1024 * 1024)
    return 0.0


def write_csv_header(file_handle, variables, rtde_r):
    """Write CSV header to file.
    
    Args:
        file_handle: Open file handle
        variables (list): List of variable names
        rtde_r: RTDEReceiveInterface instance
    """
    # Mapping of variable names to their sizes (number of columns)
    # Size 1 = single value, Size > 1 = vector
    variable_sizes = {
        # Single values
        "timestamp": 1,
        "actual_execution_time": 1,
        "robot_mode": 1,
        "robot_status_bits": 1,
        "safety_mode": 1,
        "safety_status_bits": 1,
        "speed_scaling": 1,
        "target_speed_fraction": 1,
        "actual_momentum": 1,
        "actual_main_voltage": 1,
        "actual_robot_voltage": 1,
        "actual_robot_current": 1,
        "actual_digital_input_bits": 1,
        "actual_digital_output_bits": 1,
        "runtime_state": 1,
        "standard_analog_input0": 1,
        "standard_analog_input1": 1,
        "standard_analog_output0": 1,
        "standard_analog_output1": 1,
        "payload": 1,
        "speed_scaling_combined": 1,
        # Vectors of size 6
        "target_q": 6,
        "target_qd": 6,
        "target_qdd": 6,
        "target_current": 6,
        "target_moment": 6,
        "actual_q": 6,
        "actual_qd": 6,
        "actual_current": 6,
        "joint_control_output": 6,
        "actual_TCP_pose": 6,
        "actual_TCP_speed": 6,
        "actual_TCP_force": 6,
        "target_TCP_pose": 6,
        "target_TCP_speed": 6,
        "joint_temperatures": 6,
        "actual_joint_voltage": 6,
        "payload_inertia": 6,
        "ft_raw_wrench": 6,
        "actual_current_as_torque": 6,
        # Vectors of size 3
        "actual_tool_accelerometer": 3,
        "payload_cog": 3,
        # Vectors of size 6 (joint_mode is int32 vector)
        "joint_mode": 6,
    }
    
    header_parts = []
    for var in variables:
        size = variable_sizes.get(var, 1)  # Default to size 1 if unknown
        if size > 1:
            for j in range(size):
                header_parts.append(f"{var}_{j}")
        else:
            header_parts.append(var)
    
    file_handle.write(",".join(header_parts) + "\n")
    file_handle.flush()


def write_csv_row(file_handle, variables, rtde_r, timestamp_offset=0.0):
    """Write a single row of data to CSV file.
    
    Args:
        file_handle: Open file handle
        variables (list): List of variable names
        rtde_r: RTDEReceiveInterface instance
        timestamp_offset (float): Offset to convert RTDE timestamp to physical time (wall-clock time)
    """
    row_parts = []
    for var in variables:
        try:
            # Single values
            if var == "timestamp":
                # Convert RTDE timestamp (relative) to physical time (wall-clock)
                physical_timestamp = rtde_r.getTimestamp() + timestamp_offset
                row_parts.append(f"{physical_timestamp:.6f}")
            elif var == "actual_execution_time":
                row_parts.append(f"{rtde_r.getActualExecutionTime():.6f}")
            elif var == "robot_mode":
                row_parts.append(f"{float(rtde_r.getRobotMode()):.6f}")
            elif var == "robot_status_bits":
                row_parts.append(f"{float(rtde_r.getRobotStatus()):.6f}")
            elif var == "safety_mode":
                row_parts.append(f"{float(rtde_r.getSafetyMode()):.6f}")
            elif var == "safety_status_bits":
                row_parts.append(f"{float(rtde_r.getSafetyStatusBits()):.6f}")
            elif var == "speed_scaling":
                row_parts.append(f"{rtde_r.getSpeedScaling():.6f}")
            elif var == "target_speed_fraction":
                row_parts.append(f"{rtde_r.getTargetSpeedFraction():.6f}")
            elif var == "actual_momentum":
                row_parts.append(f"{rtde_r.getActualMomentum():.6f}")
            elif var == "actual_main_voltage":
                row_parts.append(f"{rtde_r.getActualMainVoltage():.6f}")
            elif var == "actual_robot_voltage":
                row_parts.append(f"{rtde_r.getActualRobotVoltage():.6f}")
            elif var == "actual_robot_current":
                row_parts.append(f"{rtde_r.getActualRobotCurrent():.6f}")
            elif var == "actual_digital_input_bits":
                row_parts.append(f"{float(rtde_r.getActualDigitalInputBits()):.6f}")
            elif var == "actual_digital_output_bits":
                row_parts.append(f"{float(rtde_r.getActualDigitalOutputBits()):.6f}")
            elif var == "runtime_state":
                row_parts.append(f"{float(rtde_r.getRuntimeState()):.6f}")
            elif var == "standard_analog_input0":
                row_parts.append(f"{rtde_r.getStandardAnalogInput0():.6f}")
            elif var == "standard_analog_input1":
                row_parts.append(f"{rtde_r.getStandardAnalogInput1():.6f}")
            elif var == "standard_analog_output0":
                row_parts.append(f"{rtde_r.getStandardAnalogOutput0():.6f}")
            elif var == "standard_analog_output1":
                row_parts.append(f"{rtde_r.getStandardAnalogOutput1():.6f}")
            elif var == "payload":
                row_parts.append(f"{rtde_r.getPayload():.6f}")
            elif var == "speed_scaling_combined":
                row_parts.append(f"{rtde_r.getSpeedScalingCombined():.6f}")
            # Vector values (size 6)
            elif var == "target_q":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetQ()])
            elif var == "target_qd":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetQd()])
            elif var == "target_qdd":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetQdd()])
            elif var == "target_current":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetCurrent()])
            elif var == "target_moment":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetMoment()])
            elif var == "actual_q":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualQ()])
            elif var == "actual_qd":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualQd()])
            elif var == "actual_current":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualCurrent()])
            elif var == "joint_control_output":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getJointControlOutput()])
            elif var == "actual_TCP_pose":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualTCPPose()])
            elif var == "actual_TCP_speed":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualTCPSpeed()])
            elif var == "actual_TCP_force":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualTCPForce()])
            elif var == "target_TCP_pose":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetTCPPose()])
            elif var == "target_TCP_speed":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getTargetTCPSpeed()])
            elif var == "joint_temperatures":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getJointTemperatures()])
            elif var == "actual_joint_voltage":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualJointVoltage()])
            elif var == "payload_inertia":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getPayloadInertia()])
            elif var == "ft_raw_wrench":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getFtRawWrench()])
            elif var == "actual_current_as_torque":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualCurrentAsTorque()])
            # Vector values (size 3)
            elif var == "actual_tool_accelerometer":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getActualToolAccelerometer()])
            elif var == "payload_cog":
                row_parts.extend([f"{v:.6f}" for v in rtde_r.getPayloadCog()])
            # Vector values (size 6, int32)
            elif var == "joint_mode":
                row_parts.extend([f"{float(v):.6f}" for v in rtde_r.getJointMode()])
            else:
                # Unknown variable - try to write placeholder
                # Check if it might be a vector by looking at the header
                row_parts.append("0.000000")
        except Exception as e:
            # If we can't get the variable, write placeholder
            # For vectors, we need to write multiple placeholders
            # We'll use the header size to determine how many
            var_size = 1  # Default to 1
            if var in ["target_q", "target_qd", "target_qdd", "target_current", "target_moment",
                      "actual_q", "actual_qd", "actual_current", "joint_control_output",
                      "actual_TCP_pose", "actual_TCP_speed", "actual_TCP_force",
                      "target_TCP_pose", "target_TCP_speed", "joint_temperatures",
                      "actual_joint_voltage", "payload_inertia", "ft_raw_wrench",
                      "actual_current_as_torque", "joint_mode"]:
                var_size = 6
            elif var in ["actual_tool_accelerometer", "payload_cog"]:
                var_size = 3
            
            row_parts.extend(["0.000000"] * var_size)
    
    file_handle.write(",".join(row_parts) + "\n")
    file_handle.flush()


def main(args):
    """Main entry point allowing external calls

    Args:
      args ([str]): command line parameter list
    """
    args = parse_args(args)
    dt = 1 / args.frequency
    
    # Parse record variables: command-line argument takes precedence, then file, then all variables
    record_variables = []
    if args.variables:
        # Use command-line argument
        record_variables = [v.strip() for v in args.variables.split(',')]
        print(f"Recording specified variables (from command line): {', '.join(record_variables)}")
    else:
        # Try to load from file
        record_variables = load_variables_from_file()
        if record_variables:
            print(f"Recording specified variables (from record_variables_input.txt): {', '.join(record_variables)}")
        else:
            print("Recording all available variables")
    
    rtde_r = RTDEReceive(args.ip, args.frequency)
    
    # File splitting configuration
    max_file_size_mb = args.max_file_size
    max_duration_seconds = args.max_duration * 60.0 if args.max_duration else None
    file_number = 1
    current_session_timestamp = None  # Timestamp for current recording session
    current_output_file = None
    
    # Recording state tracking
    is_recording = False
    current_file_handle = None
    stable_state_count = 0  # Count consecutive checks with same state
    last_runtime_state = None
    stable_state_threshold = 3  # Require 3 consecutive checks (3 seconds) of stable state
    has_recorded_before = False  # Track if we've recorded in this session
    
    # Timestamp conversion: track first RTDE timestamp and corresponding wall-clock time
    first_rtde_timestamp = None
    timestamp_offset = 0.0  # Offset to convert RTDE timestamp to physical time
    
    print("Waiting for robot to be in PLAYING state to start recording...")
    print("Press [Ctrl-C] to end recording.")
    
    i = 0
    samples_since_last_check = 0
    check_interval = int(args.frequency)  # Check every second
    
    try:
        while True:
            t_start = rtde_r.initPeriod()
            
            # Check runtime_state periodically
            if samples_since_last_check >= check_interval:
                samples_since_last_check = 0
                
                try:
                    runtime_state = rtde_r.getRuntimeState()
                    
                    # Track stable state for debouncing
                    if runtime_state == last_runtime_state:
                        stable_state_count += 1
                    else:
                        stable_state_count = 0
                        last_runtime_state = runtime_state
                    
                    # Start recording when PLAYING and not currently recording
                    if runtime_state == RUNTIME_STATE_PLAYING and not is_recording:
                        if stable_state_count >= stable_state_threshold:
                            # Generate new timestamp for this recording session
                            current_session_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            
                            # Reset file number for new session
                            file_number = 1
                            
                            # Generate output filename with new timestamp
                            current_output_file = add_timestamp_to_filename(args.output, 
                                                                            file_number if (max_file_size_mb or max_duration_seconds or has_recorded_before) else None,
                                                                            current_session_timestamp)
                            
                            # Capture first RTDE timestamp and corresponding wall-clock time for conversion
                            first_rtde_timestamp = rtde_r.getTimestamp()
                            wall_clock_time = time.time()
                            timestamp_offset = wall_clock_time - first_rtde_timestamp
                            
                            # Open file and write header
                            current_file_handle = open(current_output_file, 'w')
                            write_csv_header(current_file_handle, record_variables, rtde_r)
                            file_start_time = time.time()
                            is_recording = True
                            has_recorded_before = True
                            stable_state_count = 0
                            print(f"\nRobot is PLAYING - Recording started: {current_output_file}")
                            print(f"  Timestamp conversion: RTDE timestamps converted to physical time")
                            if max_file_size_mb:
                                print(f"  Max file size: {max_file_size_mb} MB")
                            if max_duration_seconds:
                                print(f"  Max duration: {args.max_duration} minutes per file")
                    
                    # Stop recording when not PLAYING and currently recording
                    elif runtime_state != RUNTIME_STATE_PLAYING and is_recording:
                        if stable_state_count >= 2:  # Require 2 seconds of stable non-PLAYING state
                            if current_file_handle:
                                current_file_handle.close()
                                current_file_handle = None
                            is_recording = False
                            stable_state_count = 0
                            state_names = {0: "STOPPING", 1: "STOPPED", 3: "PAUSING", 4: "PAUSED", 5: "RESUMING"}
                            state_name = state_names.get(runtime_state, f"UNKNOWN({runtime_state})")
                            print(f"\nRobot is {state_name} - Recording stopped")
                
                except Exception as e:
                    # If we can't get runtime_state, continue but warn
                    if is_recording:
                        print(f"\nWarning: Could not check runtime_state: {e}")
            
            # Write data row only if recording
            if is_recording and current_file_handle:
                write_csv_row(current_file_handle, record_variables, rtde_r, timestamp_offset)
            
                # Check if we need to split files (only when recording)
                if is_recording and (max_file_size_mb or max_duration_seconds):
                    should_split = False
                    split_reason = ""
                    
                    # Check file size limit
                    if max_file_size_mb:
                        current_size_mb = get_file_size_mb(current_output_file)
                        if current_size_mb >= max_file_size_mb:
                            should_split = True
                            split_reason = f"file size ({current_size_mb:.2f} MB >= {max_file_size_mb} MB)"
                    
                    # Check duration limit
                    if max_duration_seconds:
                        elapsed_seconds = time.time() - file_start_time
                        if elapsed_seconds >= max_duration_seconds:
                            should_split = True
                            split_reason = f"duration ({elapsed_seconds/60:.1f} min >= {args.max_duration} min)"
                    
                    # Split to new file if needed
                    if should_split:
                        # Close current file
                        if current_file_handle:
                            current_file_handle.close()
                        print(f"\nFile split: {split_reason}")
                        file_number += 1
                        current_output_file = add_timestamp_to_filename(args.output, file_number, current_session_timestamp)
                        
                        # Open new file
                        current_file_handle = open(current_output_file, 'w')
                        write_csv_header(current_file_handle, record_variables, rtde_r)
                        file_start_time = time.time()
                        print(f"New file started: {current_output_file}")
            
            # Status display
            if i % 10 == 0:
                try:
                    runtime_state = rtde_r.getRuntimeState()
                    state_names = {0: "STOPPING", 1: "STOPPED", 2: "PLAYING", 3: "PAUSING", 4: "PAUSED", 5: "RESUMING"}
                    state_name = state_names.get(runtime_state, f"UNKNOWN({runtime_state})")
                    
                    if is_recording:
                        # Show full status when recording
                        status_msg = f"{i:6d} samples | State: {state_name} [RECORDING]"
                        if max_file_size_mb:
                            current_size_mb = get_file_size_mb(current_output_file)
                            status_msg += f" | Size: {current_size_mb:.2f} MB"
                        if max_duration_seconds and file_start_time:
                            elapsed_seconds = time.time() - file_start_time
                            status_msg += f" | Time: {elapsed_seconds/60:.1f} min"
                    else:
                        # Show only state when not recording
                        status_msg = f"State: {state_name} [WAITING]"
                except:
                    # Fallback if we can't get runtime_state
                    if is_recording:
                        status_msg = f"{i:6d} samples [RECORDING]"
                    else:
                        status_msg = "State: UNKNOWN [WAITING]"
                
                sys.stdout.write("\r" + status_msg)
                sys.stdout.flush()
            
            rtde_r.waitPeriod(t_start)
            i += 1
            samples_since_last_check += 1

    except KeyboardInterrupt:
        if current_file_handle:
            current_file_handle.close()
        print(f"\nData recording stopped. Total samples: {i}")
        if is_recording and file_number > 1:
            print(f"Recorded {file_number} file(s)")


if __name__ == "__main__":
    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parse_args(['--help'])
        sys.exit(0)
    
    main(sys.argv[1:])
