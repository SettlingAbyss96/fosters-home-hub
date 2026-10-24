package android.app.job;

import android.content.Context;

public abstract class JobService extends Context {
    public abstract boolean onStartJob(JobParameters params);

    public abstract boolean onStopJob(JobParameters params);
}
