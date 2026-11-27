import pandas as pd


def extract_measurements(input_csv, output_csv, threshold_ua=100000):
    # 1. Load the CSV
    df = pd.read_csv(input_csv)

    # 2. Identify rows where current exceeds the threshold
    is_active = df["Current(uA)"] > threshold_ua

    # 3. Assign a unique group ID to each contiguous burst above the threshold
    burst_id = (is_active != is_active.shift()).cumsum()

    # 4. Filter to only the active rows and group by burst_id
    measurements = (
        df[is_active]
        .groupby(burst_id)
        .agg(
            measurement_start_ms=("Timestamp(ms)", "min"),
            measurement_end_ms=("Timestamp(ms)", "max"),
        )
        .reset_index(drop=True)
    )

    # 5. Calculate duration
    measurements["measurement_duration_ms"] = (
        measurements["measurement_end_ms"]
        - measurements["measurement_start_ms"]
    )

    # 6. Save to the output CSV
    measurements.to_csv(output_csv, index=False)


# --- Usage Example ---
extract_measurements("second_measurement.csv", "second_summary.csv", 10000)
