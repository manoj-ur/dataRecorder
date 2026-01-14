from rtde_receive import RTDEReceiveInterface as RTDEReceive
import time
import argparse
import sys
from datetime import datetime
import os


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
    # Generate base timestamp for consistent naming across file splits
    base_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    current_output_file = add_timestamp_to_filename(args.output, 
                                                    file_number if (max_file_size_mb or max_duration_seconds) else None,
                                                    base_timestamp)
    
    # Start first file
    rtde_r.startFileRecording(current_output_file, record_variables)
    file_start_time = time.time()
    print(f"Data recording started, output file: {current_output_file}")
    if max_file_size_mb:
        print(f"  Max file size: {max_file_size_mb} MB")
    if max_duration_seconds:
        print(f"  Max duration: {args.max_duration} minutes per file")
    print("Press [Ctrl-C] to end recording.")
    
    i = 0
    samples_since_last_check = 0
    check_interval = int(args.frequency)  # Check every second
    
    try:
        while True:
            t_start = rtde_r.initPeriod()
            
            # Check if we need to split files
            if (max_file_size_mb or max_duration_seconds) and samples_since_last_check >= check_interval:
                samples_since_last_check = 0
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
                    rtde_r.stopFileRecording()
                    print(f"\nFile split: {split_reason}")
                    file_number += 1
                    current_output_file = add_timestamp_to_filename(args.output, file_number, base_timestamp)
                    file_start_time = time.time()
                    rtde_r.startFileRecording(current_output_file, record_variables)
                    print(f"New file started: {current_output_file}")
            
            if i % 10 == 0:
                status_msg = f"{i:6d} samples"
                if max_file_size_mb:
                    current_size_mb = get_file_size_mb(current_output_file)
                    status_msg += f" | Size: {current_size_mb:.2f} MB"
                if max_duration_seconds:
                    elapsed_seconds = time.time() - file_start_time
                    status_msg += f" | Time: {elapsed_seconds/60:.1f} min"
                sys.stdout.write("\r" + status_msg)
                sys.stdout.flush()
            
            rtde_r.waitPeriod(t_start)
            i += 1
            samples_since_last_check += 1

    except KeyboardInterrupt:
        rtde_r.stopFileRecording()
        print(f"\nData recording stopped. Total samples: {i}")
        if file_number > 1:
            print(f"Recorded {file_number} file(s)")


if __name__ == "__main__":
    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parse_args(['--help'])
        sys.exit(0)
    
    main(sys.argv[1:])
