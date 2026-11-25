import csv
import statistics

# Configuration
CSV_FILE = "first_measurement.csv"  # Replace with your actual file path
START_DELAY_MS = 20000
THRESHOLD_UA = 100_000.0  # 100 mA = 100,000 uA

standby_currents = []
recording_currents = []

with open(CSV_FILE, mode="r", newline="", encoding="utf-8") as f:
  reader = csv.DictReader(f)

  for row in reader:
    timestamp = float(row["Timestamp(ms)"])

    # Skip initial delay
    if timestamp < START_DELAY_MS:
      continue

    current_ua = float(row["Current(uA)"])

    if current_ua < THRESHOLD_UA:
      standby_currents.append(current_ua)
    elif current_ua > THRESHOLD_UA:
      recording_currents.append(current_ua)


def print_stats(label, values):
  if len(values) > 1:
    avg = statistics.mean(values)
    std = statistics.stdev(values)
    print(f"{label} (n={len(values)} samples):")
    print(f"  Average: {avg:.3f} uA ({avg / 1000:.3f} mA)")
    print(f"  Std Dev: {std:.3f} uA ({std / 1000:.3f} mA)\n")
  elif len(values) == 1:
    print(f"{label} (n=1 sample):")
    print(f"  Average: {values[0]:.3f} uA ({values[0] / 1000:.3f} mA)")
    print("  Std Dev: N/A (need at least 2 samples)\n")
  else:
    print(f"{label}: No samples found.\n")


print(f"Results after {START_DELAY_MS} ms delay:\n" + "-" * 40)
print_stats("Standby (< 100 mA)", standby_currents)
print_stats("Recording (> 100 mA)", recording_currents)
