#!/usr/bin/env python3
"""
Interactive plotting script for RTDE CSV recording files using Plotly.

Plotly provides interactive plots that work in web browsers without display issues.

Usage:
    python3 plot_data_plotly.py [options]

Examples:
    # Plot all CSV files in current directory
    python3 plot_data_plotly.py

    # Plot specific files
    python3 plot_data_plotly.py --files robot_data_2026-01-13_23-01-19_001.csv

    # Plot specific variables
    python3 plot_data_plotly.py --variables actual_TCP_force_0,actual_TCP_force_1

    # Save as HTML instead of opening in browser
    python3 plot_data_plotly.py --save-html plots.html
"""

import pandas as pd
import glob
import os
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Try to import plotly
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.offline as pyo
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("Warning: plotly is not available. Please install it:")
    print("  pip install plotly")
    print("\nYou can still use this script to read and save CSV data.")


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


def plot_tcp_force_plotly(df, time_column='relative_time', save_path=None, show=True):
    """
    Plot TCP force components using Plotly.
    
    Args:
        df: DataFrame with data
        time_column: Column to use for x-axis
        save_path: Path to save HTML file (optional)
        show: Whether to open in browser (default: True)
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly is not available. Cannot create plots.")
        return None
    
    force_cols = [col for col in df.columns if 'actual_TCP_force' in col]
    
    if not force_cols:
        print("No TCP force columns found")
        return None
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=('TCP Forces (X, Y, Z)', 'TCP Torques (Rx, Ry, Rz)'),
        vertical_spacing=0.1
    )
    
    # Convert time column to numpy array for plotting
    x_data = df[time_column].values
    
    # Plot forces (first 3 components)
    force_labels = ['X', 'Y', 'Z']
    for i in range(min(3, len(force_cols))):
        if f'actual_TCP_force_{i}' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=df[f'actual_TCP_force_{i}'].values,
                    mode='lines',
                    name=f'Force {force_labels[i]}',
                    line=dict(width=1)
                ),
                row=1, col=1
            )
    
    # Plot moments (last 3 components)
    for i in range(3, min(6, len(force_cols))):
        if f'actual_TCP_force_{i}' in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=df[f'actual_TCP_force_{i}'].values,
                    mode='lines',
                    name=f'Torque {force_labels[i-3]}',
                    line=dict(width=1)
                ),
                row=2, col=1
            )
    
    # Update axes labels
    fig.update_xaxes(title_text=f"Time ({time_column})", row=2, col=1)
    fig.update_yaxes(title_text="Force (N)", row=1, col=1)
    fig.update_yaxes(title_text="Torque (Nm)", row=2, col=1)
    
    # Update layout
    fig.update_layout(
        height=800,
        title_text="TCP Forces and Torques",
        hovermode='x unified',
        showlegend=True
    )
    
    # Save or show
    if save_path:
        fig.write_html(save_path)
        print(f"Saved: {save_path}")
        if show:
            fig.show()
    elif show:
        fig.show()
    
    return fig


def plot_variables_plotly(df, variables, time_column='relative_time', save_path=None, show=True):
    """
    Plot specified variables using Plotly.
    
    Args:
        df: DataFrame with data
        variables: List of variable names to plot
        time_column: Column to use for x-axis
        save_path: Path to save HTML file (optional)
        show: Whether to open in browser (default: True)
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly is not available. Cannot create plots.")
        return None
    
    if not variables:
        print("No variables specified")
        return None
    
    # Create subplots
    n_vars = len(variables)
    fig = make_subplots(
        rows=n_vars, cols=1,
        subplot_titles=variables,
        vertical_spacing=0.05
    )
    
    x_data = df[time_column].values
    
    for i, var in enumerate(variables):
        if var in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=df[var].values,
                    mode='lines',
                    name=var,
                    line=dict(width=1),
                    showlegend=True
                ),
                row=i+1, col=1
            )
            fig.update_yaxes(title_text=var, row=i+1, col=1)
        else:
            print(f"Warning: Variable '{var}' not found in data")
    
    # Update x-axis label on last subplot
    fig.update_xaxes(title_text=f"Time ({time_column})", row=n_vars, col=1)
    
    # Update layout
    fig.update_layout(
        height=300 * n_vars,
        title_text="Variable Plots",
        hovermode='x unified',
        showlegend=True
    )
    
    # Save or show
    if save_path:
        fig.write_html(save_path)
        print(f"Saved: {save_path}")
        if show:
            fig.show()
    elif show:
        fig.show()
    
    return fig


def plot_by_session_plotly(df, variable, time_column='relative_time', save_path=None, show=True):
    """
    Plot a variable grouped by recording session using Plotly.
    
    Args:
        df: DataFrame with data
        variable: Variable name to plot
        time_column: Column to use for x-axis
        save_path: Path to save HTML file (optional)
        show: Whether to open in browser (default: True)
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly is not available. Cannot create plots.")
        return None
    
    if 'session_timestamp' not in df.columns:
        print("No session information found")
        return None
    
    if variable not in df.columns:
        print(f"Variable '{variable}' not found in data")
        return None
    
    fig = go.Figure()
    
    for session in df['session_timestamp'].unique():
        session_df = df[df['session_timestamp'] == session]
        fig.add_trace(
            go.Scatter(
                x=session_df[time_column].values,
                y=session_df[variable].values,
                mode='lines',
                name=f'Session: {session}',
                line=dict(width=1)
            )
        )
    
    fig.update_layout(
        title=f'{variable} by Recording Session',
        xaxis_title=f'Time ({time_column})',
        yaxis_title=variable,
        hovermode='x unified',
        height=600,
        showlegend=True
    )
    
    # Save or show
    if save_path:
        fig.write_html(save_path)
        print(f"Saved: {save_path}")
        if show:
            fig.show()
    elif show:
        fig.show()
    
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
        description="Interactive plotting script for RTDE CSV files using Plotly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot all CSV files in current directory
  python3 plot_data_plotly.py

  # Plot specific files
  python3 plot_data_plotly.py --files robot_data_2026-01-13_23-01-19_001.csv

  # Plot specific variables
  python3 plot_data_plotly.py --variables actual_TCP_force_0,actual_TCP_force_1

  # Save as HTML instead of opening in browser
  python3 plot_data_plotly.py --save-html plots.html

  # Save without opening
  python3 plot_data_plotly.py --save-html plots.html --no-show
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
        '--save-html',
        help='Save plots as HTML file instead of opening in browser',
        default=None
    )
    
    parser.add_argument(
        '--no-show',
        action='store_true',
        help='Do not open plots in browser (only save if --save-html is specified)'
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
    
    if not PLOTLY_AVAILABLE:
        print("Error: plotly is not installed.")
        print("Install it with: pip install plotly")
        return
    
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
    
    # Determine show/save settings
    show_plots = not args.no_show
    save_html = args.save_html if args.save_html else None
    
    # Generate plots
    figures = []
    
    # Plot TCP forces
    if args.plot_type in ['tcp_force', 'all']:
        if 'actual_TCP_force_0' in df.columns:
            html_path = save_html if save_html else 'tcp_forces.html'
            fig = plot_tcp_force_plotly(df, time_column=args.time_column, 
                                       save_path=html_path, show=show_plots)
            if fig:
                figures.append(fig)
                if not save_html:
                    save_html = 'tcp_forces.html'  # Auto-save if not specified
    
    # Plot specific variables
    if args.plot_type in ['variables', 'all']:
        if args.variables:
            variables = [v.strip() for v in args.variables.split(',')]
            html_path = save_html if save_html else 'variables.html'
            fig = plot_variables_plotly(df, variables, time_column=args.time_column,
                                       save_path=html_path, show=show_plots)
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
                html_path = save_html if save_html else f'{var}_by_session.html'
                fig = plot_by_session_plotly(df, var, time_column=args.time_column,
                                            save_path=html_path, show=show_plots)
                if fig:
                    figures.append(fig)
    
    if figures:
        print(f"\nGenerated {len(figures)} plot(s)")
        if save_html:
            print(f"Plots saved to HTML file(s)")
        if show_plots and not save_html:
            print("Plots opened in browser")
    else:
        print("\nNo plots were generated")


if __name__ == "__main__":
    main()
