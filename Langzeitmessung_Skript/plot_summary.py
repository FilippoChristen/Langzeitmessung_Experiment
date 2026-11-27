import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('second_summary.csv')

plt.plot(df['measurement_start_ms'], df['measurement_duration_ms'], marker='o')
plt.xlabel('Measurement Start (ms)')
plt.ylabel('Measurement Duration (ms)')
plt.title('Measurement Duration over Start Time')
plt.grid(True)
plt.show()
