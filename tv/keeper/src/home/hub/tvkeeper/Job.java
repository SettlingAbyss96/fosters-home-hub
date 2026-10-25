package home.hub.tvkeeper;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** Every 15 minutes, in case something switched debugging off without a reboot, and two minutes
 * after the private DNS was parked for a wrong clock (Keeper.keepTime) */
public final class Job extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        Keeper.enforce(this);
        return false;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return false;
    }
}
