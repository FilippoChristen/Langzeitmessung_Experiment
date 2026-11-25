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

  # Guard against empty slices
  if df.empty:
    print("No data found in the specified time range.")
    return

  # 3. Convert time to relative seconds starting from 0, and current to mA
  df = df.copy()
  t0_ms = df["Timestamp(ms)"].iloc[0]
  df["Time(s)"] = (df["Timestamp(ms)"] - t0_ms) / 1000.0
  df["Current(mA)"] = df["Current(uA)"] / 1000.0

  # 4. Plot the data
  df.plot(
      x="Time(s)",
      y="Current(mA)",
      kind="line",
      marker="o",
      legend=False,
  )

  plt.yscale("log")
  plt.xlabel("Time (s)")
  plt.ylabel("Current (mA)")
  plt.title("Current vs. Time")
  plt.grid(True, which="both", linestyle="--", alpha=0.6)
  plt.show()


# --- Usage Examples ---

# Plot the entire file:
# plot_csv("first_measurement.csv")

# Plot only between 800,000 ms and 810,000 ms (shown as 0 to 10 s):
plot_csv("first_measurement.csv", start_ms=800000, end_ms=810000)
