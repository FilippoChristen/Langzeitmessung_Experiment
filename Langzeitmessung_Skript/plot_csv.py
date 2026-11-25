import matplotlib.pyplot as plt
import pandas as pd


def plot_csv(file_path, start_ms=None, end_ms=None):
    # 1. Load the CSV
    df = pd.read_csv(file_path)

    # 2. Filter the time range if start_ms or end_ms are provided
    if start_ms is not None:
        df = df[df["Timestamp(ms)"] >= start_ms]
    if end_ms is not None:
        df = df[df["Timestamp(ms)"] <= end_ms]

    # 3. Plot the data
    df.plot(
        x="Timestamp(ms)",
        y="Current(uA)",
        kind="line",
        marker="o",
        legend=False,
    )

    plt.ylabel("Current (uA)")
    plt.title("Current vs. Timestamp")
    plt.grid(True)
    plt.show()


# --- Usage Examples ---

# Plot the entire file:
#plot_csv("first_measurement.csv")

# Plot only between 20 ms and 90 ms:
plot_csv("first_measurement.csv", start_ms=390000, end_ms=410000)

# Plot everything from 50 ms to the end:
#plot_csv("data.csv", start_ms=50)
