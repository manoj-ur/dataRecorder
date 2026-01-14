#!/usr/bin/env python3
"""
Script to read and plot data from RTDE CSV recording files.

Usage:
    python3 plot_data.py [options]

Examples:
    # Plot all CSV files in current directory
    python3 plot_data.py

    # Plot specific files
    python3 plot_data.py --files robot_data_2026-01-13_23-01-19_001.csv

    # Plot specific variables
    python3 plot_data.py --variables actual_TCP_force_0,actual_TCP_force_1

    # Use real time instead of relative time
    python3 plot_data.py --time-column real_time
"""

# Try to use an interactive backend for matplotlib (works with remote displays like AnyDesk)
import matplotlib
try:
    matplotlib.use('Qt5Agg')  # Try Qt5Agg first (works with most displays)
except:
    try:
        matplotlib.use('TkAgg')  # Fallback to TkAgg
    except:
        pass  # Use default backend

import pandas as pd
import glob
import os
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Try to import matplotlib with helpful error message
try:
    import matplotlib.pyplot as plt
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError as e:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib is not available. Plotting features will be disabled.")
    print(f"Error: {e}")
    print("\nTo fix this, try one of the following:")
    print("  1. Install matplotlib: pip install matplotlib")
    print("  2. Fix NumPy compatibility: pip install 'numpy<2' matplotlib")
    print("  3. Or upgrade matplotlib: pip install --upgrade matplotlib")
    print("\nYou can still use this script to read and save CSV data without plotting.")


def convert_timestamps_from_filename(csv_file):
    """
    Convert RTDE timestamps to real clock time using filename timestamp.
    
    Args:
        csv_file: Path to CSV file
        
    Returns:
        DataFrame with converted timestamps and file start time
    """
    # Extract timestamp from filename
    match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', csv_file)
    if match:
        file_timestamp_str = match.group(1)
        file_start_time = datetime.strptime(file_timestamp_str, "%Y-%m-%d_%H-%M-%S")
    else:
        # Fallback to file creation time
        file_start_time = datetime.fromtimestamp(os.path.getctime(csv_file))
    
    # Read CSV
    df = pd.read_csv(csv_file)
    
    # Get first timestamp value
    if len(df) > 0:
        first_timestamp = df['timestamp'].iloc[0]
        # Calculate controller start time
        controller_start_time = file_start_time - timedelta(seconds=first_timestamp)
        
        # Convert all timestamps to real clock time
        df['real_time'] = df['timestamp'].apply(
            lambda ts: controller_start_time + timedelta(seconds=ts)
        )
        
        # Also add relative time from start of recording (in seconds)
        df['relative_time'] = df['timestamp'] - first_timestamp
        
        return df, file_start_time
    else:
        return df, file_start_time


def read_all_csv_files(pattern="robot_data_*.csv", directory=".", specific_files=None):
    """
    Read all CSV files matching the pattern and combine them.
    
    Args:
        pattern: File pattern to match (default: "robot_data_*.csv")
        directory: Directory to search (default: current directory)
        specific_files: List of specific file paths to read (optional)
        
    Returns:
        Dictionary with session data and combined dataframe
    """
    if specific_files:
        csv_files = [f for f in specific_files if os.path.exists(f)]
    else:
        csv_files = sorted(glob.glob(os.path.join(directory, pattern)))
    
    if not csv_files:
        print(f"No CSV files found matching pattern: {pattern}")
        return None, None
    
    print(f"Found {len(csv_files)} CSV file(s)")
    
    all_dataframes = []
    session_info = {}
    
    for csv_file in csv_files:
        print(f"Reading: {os.path.basename(csv_file)}")
        try:
            df, file_start_time = convert_timestamps_from_filename(csv_file)
            
            if len(df) > 0:
                # Extract session info from filename
                match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_(\d{3})', csv_file)
                if match:
                    session_timestamp = match.group(1)
                    file_number = int(match.group(2))
                else:
                    # Try without file number
                    match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', csv_file)
                    if match:
                        session_timestamp = match.group(1)
                        file_number = 1
                    else:
                        session_timestamp = file_start_time.strftime("%Y-%m-%d_%H-%M-%S")
                        file_number = 1
                
                # Add metadata columns
                df['session_timestamp'] = session_timestamp
                df['file_number'] = file_number
                df['source_file'] = os.path.basename(csv_file)
                
                all_dataframes.append(df)
                
                # Store session info
                if session_timestamp not in session_info:
                    session_info[session_timestamp] = {
                        'start_time': file_start_time,
                        'files': [],
                        'total_samples': 0
                    }
                session_info[session_timestamp]['files'].append(csv_file)
                session_info[session_timestamp]['total_samples'] += len(df)
            else:
                print(f"  Warning: {os.path.basename(csv_file)} is empty")
        except Exception as e:
            print(f"  Error reading {os.path.basename(csv_file)}: {e}")
    
    # Combine all dataframes
    if all_dataframes:
        combined_df = pd.concat(all_dataframes, ignore_index=True)
        combined_df = combined_df.sort_values('real_time')
        
        # Reset relative time to be from first recording
        first_time = combined_df['real_time'].iloc[0]
        combined_df['relative_time'] = (combined_df['real_time'] - first_time).dt.total_seconds()
        
        return combined_df, session_info
    else:
        return None, None


def plot_variables(df, variables, time_column='relative_time', figsize=(15, 10), save_path=None):
    """
    Plot specified variables over time.
    
    Args:
        df: DataFrame with data
        variables: List of variable names to plot
        time_column: Column to use for x-axis ('relative_time' or 'real_time')
        figsize: Figure size tuple
        save_path: Path to save figure (optional)
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Error: matplotlib is not available. Cannot create plots.")
        print("Please install matplotlib or fix NumPy compatibility issues.")
        return None
    
    n_vars = len(variables)
    if n_vars == 0:
        print("No variables specified")
        return None
    
    # Create subplots
    fig, axes = plt.subplots(n_vars, 1, figsize=figsize, sharex=True)
    if n_vars == 1:
        axes = [axes]
    
    for i, var in enumerate(variables):
        if var in df.columns:
            # Convert to numpy arrays to avoid pandas indexing issues
            x_data = np.array(df[time_column])
            y_data = np.array(df[var])
            axes[i].plot(x_data, y_data, linewidth=0.5)
            axes[i].set_ylabel(var)
            axes[i].grid(True, alpha=0.3)
            axes[i].set_title(f'{var} over time')
        else:
            axes[i].text(0.5, 0.5, f'Variable "{var}" not found', 
                        ha='center', va='center', transform=axes[i].transAxes)
    
    axes[-1].set_xlabel(f'Time ({time_column})')
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    
    return fig


def plot_tcp_force(df, time_column='relative_time', figsize=(15, 8), save_path=None):
    """
    Plot TCP force components.
    
    Args:
        df: DataFrame with data
        time_column: Column to use for x-axis
        figsize: Figure size tuple
        save_path: Path to save figure (optional)
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Error: matplotlib is not available. Cannot create plots.")
        print("Please install matplotlib or fix NumPy compatibility issues.")
        return None
    
    force_cols = [col for col in df.columns if 'actual_TCP_force' in col]
    
    if not force_cols:
        print("No TCP force columns found")
        return None
    
    fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=True)
    
    # Convert time column to numpy array once
    x_data = np.array(df[time_column])
    
    # Plot forces (first 3 components)
    for i in range(min(3, len(force_cols))):
        if f'actual_TCP_force_{i}' in df.columns:
            y_data = np.array(df[f'actual_TCP_force_{i}'])
            axes[0].plot(x_data, y_data, 
                        label=f'Force {i} ({"XYZ"[i]})', linewidth=0.5)
    
    axes[0].set_ylabel('Force (N)')
    axes[0].set_title('TCP Forces (X, Y, Z)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Plot moments (last 3 components)
    for i in range(3, min(6, len(force_cols))):
        if f'actual_TCP_force_{i}' in df.columns:
            y_data = np.array(df[f'actual_TCP_force_{i}'])
            axes[1].plot(x_data, y_data, 
                        label=f'Torque {i-3} ({"XYZ"[i-3]})', linewidth=0.5)
    
    axes[1].set_ylabel('Torque (Nm)')
    axes[1].set_xlabel(f'Time ({time_column})')
    axes[1].set_title('TCP Torques (Rx, Ry, Rz)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    
    return fig


def plot_by_session(df, variable, time_column='relative_time', figsize=(15, 6), save_path=None):
    """
    Plot a variable grouped by recording session.
    
    Args:
        df: DataFrame with data
        variable: Variable name to plot
        time_column: Column to use for x-axis
        figsize: Figure size tuple
        save_path: Path to save figure (optional)
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Error: matplotlib is not available. Cannot create plots.")
        print("Please install matplotlib or fix NumPy compatibility issues.")
        return None
    
    if 'session_timestamp' not in df.columns:
        print("No session information found")
        return None
    
    if variable not in df.columns:
        print(f"Variable '{variable}' not found in data")
        return None
    
    fig, ax = plt.subplots(figsize=figsize)
    
    for session in df['session_timestamp'].unique():
        session_df = df[df['session_timestamp'] == session]
        # Convert to numpy arrays to avoid pandas indexing issues
        x_data = np.array(session_df[time_column])
        y_data = np.array(session_df[variable])
        ax.plot(x_data, y_data, 
               label=f'Session: {session}', linewidth=0.5, alpha=0.7)
    
    ax.set_xlabel(f'Time ({time_column})')
    ax.set_ylabel(variable)
    ax.set_title(f'{variable} by Recording Session')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    
    return fig


def list_available_variables(df):
    """List all available variables in the dataframe."""
    # Filter out metadata columns
    metadata_cols = ['timestamp', 'real_time', 'relative_time', 'session_timestamp', 
                     'file_number', 'source_file']
    variables = [col for col in df.columns if col not in metadata_cols]
    return variables


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Read and plot data from RTDE CSV recording files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot all CSV files in current directory
  python3 plot_data.py

  # Plot specific files
  python3 plot_data.py --files robot_data_2026-01-13_23-01-19_001.csv robot_data_2026-01-13_23-01-19_002.csv

  # Plot specific variables
  python3 plot_data.py --variables actual_TCP_force_0,actual_TCP_force_1

  # Use real time instead of relative time
  python3 plot_data.py --time-column real_time

  # Save plots without displaying
  python3 plot_data.py --no-show --save-dir plots/
        """
    )
    
    parser.add_argument(
        '--files', '-f',
        nargs='+',
        help='Specific CSV files to read (default: all robot_data_*.csv files)',
        default=None
    )
    
    parser.add_argument(
        '--pattern', '-p',
        help='File pattern to match (default: robot_data_*.csv)',
        default='robot_data_*.csv'
    )
    
    parser.add_argument(
        '--directory', '-d',
        help='Directory to search for CSV files (default: current directory)',
        default='.'
    )
    
    parser.add_argument(
        '--variables', '-v',
        help='Comma-separated list of variables to plot',
        default=None
    )
    
    parser.add_argument(
        '--time-column',
        choices=['relative_time', 'real_time'],
        help='Time column to use for x-axis (default: relative_time)',
        default='relative_time'
    )
    
    parser.add_argument(
        '--plot-type',
        choices=['tcp_force', 'variables', 'by_session', 'all'],
        help='Type of plot to generate (default: all)',
        default='all'
    )
    
    parser.add_argument(
        '--save-dir',
        help='Directory to save plots (default: current directory)',
        default=None
    )
    
    parser.add_argument(
        '--no-show',
        action='store_true',
        help='Do not display plots (only save them)'
    )
    
    parser.add_argument(
        '--save-csv',
        help='Save combined data to CSV file',
        default=None
    )
    
    parser.add_argument(
        '--list-variables',
        action='store_true',
        help='List all available variables and exit'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Read CSV files
    df, session_info = read_all_csv_files(
        pattern=args.pattern,
        directory=args.directory,
        specific_files=args.files
    )
    
    if df is None:
        print("No data to plot")
        return
    
    print(f"\nTotal samples: {len(df)}")
    print(f"Time range: {df['real_time'].iloc[0]} to {df['real_time'].iloc[-1]}")
    print(f"Duration: {df['relative_time'].iloc[-1]:.2f} seconds ({df['relative_time'].iloc[-1]/60:.2f} minutes)")
    print(f"\nSessions found: {len(session_info)}")
    for session, info in session_info.items():
        print(f"  {session}: {info['total_samples']} samples from {len(info['files'])} file(s)")
    
    # List variables if requested
    if args.list_variables:
        variables = list_available_variables(df)
        print(f"\nAvailable variables ({len(variables)}):")
        for var in sorted(variables):
            print(f"  {var}")
        return
    
    # Save combined CSV if requested
    if args.save_csv:
        df.to_csv(args.save_csv, index=False)
        print(f"\nSaved combined data to: {args.save_csv}")
    
    # Determine save directory
    save_dir = args.save_dir if args.save_dir else '.'
    if args.save_dir and not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    # Generate plots (only if matplotlib is available)
    figures = []
    
    if not MATPLOTLIB_AVAILABLE:
        print("\nSkipping plot generation (matplotlib not available)")
        print("Data reading and CSV export features are still available.")
    else:
        # Plot TCP forces
        if args.plot_type in ['tcp_force', 'all']:
            if 'actual_TCP_force_0' in df.columns:
                save_path = os.path.join(save_dir, 'tcp_forces.png') if save_dir else None
                fig = plot_tcp_force(df, time_column=args.time_column, save_path=save_path)
                if fig:
                    figures.append(fig)
        
        # Plot specific variables
        if args.plot_type in ['variables', 'all']:
            if args.variables:
                variables = [v.strip() for v in args.variables.split(',')]
                save_path = os.path.join(save_dir, 'variables.png') if save_dir else None
                fig = plot_variables(df, variables, time_column=args.time_column, save_path=save_path)
                if fig:
                    figures.append(fig)
            elif args.plot_type == 'variables':
                print("\nWarning: --variables not specified, skipping variable plot")
        
        # Plot by session
        if args.plot_type in ['by_session', 'all']:
            if 'session_timestamp' in df.columns:
                # Find a variable to plot
                variables = list_available_variables(df)
                if variables:
                    var = variables[0]  # Use first available variable
                    save_path = os.path.join(save_dir, f'{var}_by_session.png') if save_dir else None
                    fig = plot_by_session(df, var, time_column=args.time_column, save_path=save_path)
                    if fig:
                        figures.append(fig)
        
        # Show plots (only if display is available)
        if not args.no_show and figures:
            try:
                # Check if we're using an interactive backend
                backend = matplotlib.get_backend()
                if backend.lower() in ['agg', 'svg', 'pdf', 'ps']:
                    # Non-interactive backend - can't show, just close
                    print("\nUsing non-interactive backend. Plots saved but not displayed.")
                    print("To view plots, open the PNG files directly.")
                    plt.close('all')
                else:
                    # Interactive backend - try to show
                    plt.show()
            except Exception as e:
                # Handle any errors gracefully
                print(f"\nNote: Could not display plots interactively: {e}")
                print("Plots have been saved. You can view them by opening the PNG files.")
                plt.close('all')
        elif args.no_show and figures:
            plt.close('all')
            print("\nPlots saved (not displayed)")


if __name__ == "__main__":
    main()
