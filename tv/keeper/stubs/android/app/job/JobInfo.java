package android.app.job;

import android.content.ComponentName;

public class JobInfo {
    public static final class Builder {
        public Builder(int jobId, ComponentName jobService) {
            throw new RuntimeException("stub");
        }

        public Builder setPeriodic(long intervalMillis) {
            throw new RuntimeException("stub");
        }

        public Builder setPersisted(boolean isPersisted) {
            throw new RuntimeException("stub");
        }

        public Builder setMinimumLatency(long minLatencyMillis) {
            throw new RuntimeException("stub");
        }

        public JobInfo build() {
            throw new RuntimeException("stub");
        }
    }
}
