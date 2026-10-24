package home.hub.tvkeeper;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.ContentResolver;
import android.content.Context;
import android.provider.Settings;
import android.util.Log;

/**
 * Keeps the TV reachable for Home Assistant: ADB debugging on, and Home Assistant's approved key
 * never expiring. A Fire OS update can switch debugging off, and from then on nothing over the
 * network can switch it back, so this runs on the TV itself: at boot, after an update to this app,
 * and every 15 minutes. It only ever puts back what was already there, it never opens anything new.
 * Writing these needs WRITE_SECURE_SETTINGS, which only ADB can grant (tools/tv.py install-keeper).
 */
final class Keeper {
    static final String TAG = "TvKeeper";
    static final int JOB = 1;
    static final long EVERY_MS = 15 * 60 * 1000L;

    private Keeper() {
    }

    static void enforce(Context context) {
        ContentResolver settings = context.getContentResolver();
        try {
            if (Settings.Global.getInt(settings, "adb_enabled", 0) != 1) {
                Settings.Global.putInt(settings, "adb_enabled", 1);
                Log.i(TAG, "ADB debugging was off, switched it back on");
            }
            if (Settings.Global.getLong(settings, "adb_allowed_connection_time", -1L) != 0L) {
                Settings.Global.putLong(settings, "adb_allowed_connection_time", 0L);
                Log.i(TAG, "approved keys set to never expire again");
            }
        } catch (SecurityException e) {
            Log.w(TAG, "no WRITE_SECURE_SETTINGS, grant it over ADB: " + e.getMessage());
        }
    }

    static void schedule(Context context) {
        JobScheduler jobs = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        JobInfo job = new JobInfo.Builder(JOB, new ComponentName(context, Job.class))
                .setPeriodic(EVERY_MS)
                .setPersisted(true)
                .build();
        jobs.schedule(job);
    }
}
