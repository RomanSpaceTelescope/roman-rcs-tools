#!/usr/bin/env python3
"""
RCS Precharge Calculator - Standalone

Calculates required precharge flux and duration for each LED configuration
to achieve optimal conditioning for WFI RCS (Relative Calibration Source).

Usage:
    python precharge_calculator.py --side A --target-flux 500.0 --duration 30
    python precharge_calculator.py --side B --target-flux 500.0 --duration 30
"""

import argparse
import sys
from collections import namedtuple
import numpy as np
import pandas as pd
import os

# Find calibration file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_FILE = os.path.join(SCRIPT_DIR, '260401_sRCS_WFI_Calibration_flux_led.xlsx')

# Load calibration data on import
def _load_calibration():
    """Load flux calibration from Excel file."""
    if not os.path.exists(CALIBRATION_FILE):
        raise FileNotFoundError(f"Calibration file not found: {CALIBRATION_FILE}")

    df = pd.read_excel(CALIBRATION_FILE, sheet_name="H4RG Flux Calibration")

    # Organize into nested dict
    cal_data = {}
    for side in ['A', 'B']:
        box = 1 if side == 'A' else 2
        cal_data[side] = {}

        for band in [4, 5, 6]:
            for bank in [1, 2]:
                row = df[(df.band == band) & (df.box == box) & (df.bank == bank)]
                if len(row) > 0:
                    cal_data[side][band] = row.iloc[0].to_dict()

    return cal_data

try:
    CALIBRATION_DATA = _load_calibration()
except Exception as e:
    print(f"Warning: Could not load calibration file: {e}", file=sys.stderr)
    print("Using fallback calibration data", file=sys.stderr)
    CALIBRATION_DATA = {}

# Current-to-code calibration curves
_cmd_curve = namedtuple('Curve', ['m', 'b'])

CURRENT_CURVES = {
    'A': {
        1: {
            'high': _cmd_curve(683507.4843, 65462.8064),
            'low': _cmd_curve(273944015.3, -76.47924149),
            'ultralow': _cmd_curve(253674929.9, 164.1452529)
        },
        2: {
            'high': _cmd_curve(684726.3488, 65387.38867),
            'low': _cmd_curve(274525613.8, -147.0222373),
            'ultralow': _cmd_curve(247294249, 83.70018248)
        }
    },
    'B': {
        1: {
            'high': _cmd_curve(685056.77, 65382.47331),
            'low': _cmd_curve(274557986.4, -153.1971136),
            'ultralow': _cmd_curve(243116093.8, 93.3474194)
        },
        2: {
            'high': _cmd_curve(685523.0879, 65347.46843),
            'low': _cmd_curve(274952369.8, -166.1840521),
            'ultralow': _cmd_curve(245341211.5, 32.21601601)
        }
    }
}


def hex_to_current(side, bank, code):
    """Convert command code to current (Amps)."""
    if np.isnan(code):
        return 0

    code = int(code)
    curves = CURRENT_CURVES[side.upper()][bank]

    if code > 65536:
        current = (code - curves['high'].b) / curves['high'].m
    else:
        current = (code - curves['low'].b) / curves['low'].m

    return round(current, 10)


def current_to_hex(side, bank, current):
    """Convert current (Amps) to command code."""
    curves = CURRENT_CURVES[side.upper()][bank]
    thresh = hex_to_current(side, bank, 65535)

    if current > thresh:
        code = (current * curves['high'].m) + curves['high'].b
    else:
        code = (current * curves['low'].m) + curves['low'].b

    return round(code, 0)


def get_flux_calibration(side, band, bank):
    """Get flux calibration coefficients for a given configuration."""
    box = 1 if side.upper() == 'A' else 2
    return CALIBRATION_DATA[side.upper()][band]


def flux_to_code(side, band, bank, flux, raise_corner_case=True):
    """Convert flux (e-/pix/s) to command code."""
    f = get_flux_calibration(side, band, bank)

    if flux <= f['<= low max flux\n[e-/pix/s]']:
        code = f['L^3']*pow(flux, 3) + f['L^2']*pow(flux, 2) + f['L^1']*flux + f['L^0']
    elif (flux > f['> high min flux\n[e-/pix/s]']) and (flux < f['high max flux\n[e-/pix/s]']):
        code = f['H^3']*pow(flux, 3) + f['H^2']*pow(flux, 2) + f['H^1']*flux + f['H^0']
    else:
        if not raise_corner_case:
            if flux >= f['high max flux\n[e-/pix/s]']:
                return 0x1ffff
            elif (flux > f['<= low max flux\n[e-/pix/s]']) and (flux <= f['> high min flux\n[e-/pix/s]']):
                return 0xffff
        if flux >= f['high max flux\n[e-/pix/s]']:
            raise ValueError(f"Flux {flux:.1f} exceeds maximum {f['high max flux\n[e-/pix/s]']:.0f} for Side{side}Band{band}Bank{bank}")
        elif (flux > f['<= low max flux\n[e-/pix/s]']) and (flux <= f['> high min flux\n[e-/pix/s]']):
            raise ValueError(f"Flux {flux:.1f} in gap between low and high ranges for Side{side}Band{band}Bank{bank}")
        raise ValueError(f"Flux {flux:.1f} out of range for Side{side}Band{band}Bank{bank}")

    return int(code)


def code_to_flux(side, band, bank, code):
    """Convert command code to flux (e-/pix/s)."""
    f = get_flux_calibration(side, band, bank)

    if code > 65535*2:
        raise ValueError(f"Code {code} too large")

    if code <= 65535:
        lp = np.poly1d([f['L^3'], f['L^2'], f['L^1'], f['L^0'] - code])
        r = lp.roots
        real_roots = r[np.isreal(r)]
        if len(real_roots) == 0:
            raise ValueError(f"No real roots for code {code}")
        return real_roots[0].real
    else:
        hp = np.poly1d([f['H^3'], f['H^2'], f['H^1'], f['H^0'] - code])
        r = hp.roots
        real_roots = r[np.isreal(r)]
        if len(real_roots) == 0:
            raise ValueError(f"No real roots for code {code}")
        return real_roots[0].real


def flux_to_current(side, band, bank, flux, raise_corner_case=True):
    """Convert flux to current."""
    code = flux_to_code(side, band, bank, flux, raise_corner_case)
    return hex_to_current(side, bank, code)


def current_to_flux(side, band, bank, current):
    """Convert current to flux."""
    code = current_to_hex(side, bank, current)
    return code_to_flux(side, band, bank, code)


def calculate_precharge(side, target_flux, precharge_duration):
    """
    Calculate precharge settings for all LED configurations.

    Args:
        side: 'A' or 'B'
        target_flux: Target science flux in e-/pix/s
        precharge_duration: Precharge duration in seconds

    Returns:
        List of tuples: (led_id, precharge_flux, precharge_time_s, target_flux)
    """
    # Precharge constants (empirically determined charge factors for each band)
    pc = {
        4: 2164,  # Band 4 (1300nm)
        5: 1633 if side.upper() == 'A' else 1300,  # Band 5 (1550nm)
        6: 1040,  # Band 6 (1750nm)
    }

    # Maximum allowed code value (accounting for 17-bit range)
    MAX_CODE = 2 * 65535 - 1

    results = []

    for band in [4, 5, 6]:
        for bank in [1, 2]:
            # Calculate required flux current
            fc = flux_to_current(side, band, bank, target_flux, raise_corner_case=False) * 1e3  # Convert to mA
            ct = precharge_duration

            # Calculate precharge current needed
            precharge_current = fc * pc[band] / ct

            # Check if precharge current exceeds maximum command value
            hex_val = current_to_hex(side, bank, precharge_current / 1e3)

            if hex_val > MAX_CODE:
                # Cap at maximum available flux
                cal = get_flux_calibration(side, band, bank)
                precharge_flux = cal['high max flux\n[e-/pix/s]'] - 2
                precharge_current = flux_to_current(side, band, bank, precharge_flux) * 1e3
                ct = fc * pc[band] / precharge_current

            # Convert back to flux
            flux_pc = current_to_flux(side, band, bank, precharge_current / 1e3)

            led_id = f"LED{bank}{band}"
            results.append((led_id, flux_pc, ct, target_flux))

    return results


def print_precharge(side, target_flux, precharge_duration):
    """
    Print precharge settings for all LED configurations.

    Args:
        side: 'A' or 'B'
        target_flux: Target science flux in e-/pix/s
        precharge_duration: Precharge duration in seconds
    """
    results = calculate_precharge(side, target_flux, precharge_duration)

    for led_id, precharge_flux, precharge_time, final_flux in results:
        print(f'{led_id} PRECHARGE_FLUX = {precharge_flux:.1f} e-/pix/s PRECHARGE_TIME={precharge_time:.0f}s then {final_flux} e-/pix/s')

    print()


def main():
    parser = argparse.ArgumentParser(
        description='RCS Precharge Calculator - Calculate precharge settings for LED configurations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python precharge_calculator.py --target-flux 500.0 --duration 30
  python precharge_calculator.py --side A --target-flux 500.0 --duration 30
  python precharge_calculator.py --led LED14 --target-flux 500.0 --duration 30
  python precharge_calculator.py --led LED15 --target-flux 500.0 (just output flux)
        """
    )

    parser.add_argument('--side', choices=['A', 'B'], default='B',
                        help='Detector side (A or B, default: B)')
    parser.add_argument('--target-flux', type=float, required=True,
                        help='Target science flux level (e-/pix/s)')
    parser.add_argument('--duration', type=float, default=30.0,
                        help='Precharge duration in seconds (default: 30)')
    parser.add_argument('--led', type=str, default=None,
                        help='Specific LED (e.g., LED14, LED25). If specified, output only precharge flux.')
    parser.add_argument('--format', choices=['text', 'csv', 'json'], default='text',
                        help='Output format (default: text, ignored when --led specified)')

    args = parser.parse_args()

    try:
        results = calculate_precharge(args.side, args.target_flux, args.duration)

        # If specific LED requested, output only its precharge flux
        if args.led:
            led_results = [r for r in results if r[0] == args.led]
            if not led_results:
                print(f"Error: LED {args.led} not found", file=sys.stderr)
                print(f"Valid LEDs: LED14, LED24, LED15, LED25, LED16, LED26", file=sys.stderr)
                sys.exit(1)
            led_id, precharge_flux, precharge_time, target_flux = led_results[0]
            # Output just the precharge flux value for scripting
            print(f"{precharge_flux:.1f}")
            sys.exit(0)

        if args.format == 'text':
            print(f"\nRCS Precharge Settings")
            print(f"Side: {args.side}")
            print(f"Target Flux: {args.target_flux} e-/pix/s")
            print(f"Precharge Duration: {args.duration}s")
            print("-" * 80)
            print_precharge(args.side, args.target_flux, args.duration)

        elif args.format == 'csv':
            print("LED,Precharge_Flux_e-/pix/s,Precharge_Time_s,Target_Flux_e-/pix/s")
            for led_id, precharge_flux, precharge_time, final_flux in results:
                print(f"{led_id},{precharge_flux:.1f},{precharge_time:.1f},{final_flux}")

        elif args.format == 'json':
            import json
            output = {
                'side': args.side,
                'target_flux': args.target_flux,
                'precharge_duration': args.duration,
                'results': [
                    {
                        'led': led_id,
                        'precharge_flux': precharge_flux,
                        'precharge_time': precharge_time,
                        'target_flux': final_flux
                    }
                    for led_id, precharge_flux, precharge_time, final_flux in results
                ]
            }
            print(json.dumps(output, indent=2))

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
