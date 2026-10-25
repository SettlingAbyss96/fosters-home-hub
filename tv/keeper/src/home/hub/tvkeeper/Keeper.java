package home.hub.tvkeeper;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.ContentResolver;
import android.content.Context;
import android.provider.Settings;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Keeps the TV reachable for Home Assistant, and online: ADB debugging on, Home Assistant's approved
 * key never expiring, and the private DNS out of the way while the clock is wrong. A Fire OS update
 * can switch debugging off, and from then on nothing over the network can switch it back, so this
 * runs on the TV itself: at boot, after an update to this app, and every 15 minutes. It only ever
 * puts back what was already there, it never opens anything new. Writing these needs
 * WRITE_SECURE_SETTINGS, which only ADB can grant (tools/tv.py install-keeper).
 */
final class Keeper {
    static final String TAG = "TvKeeper";
    static final int JOB = 1;
    static final int JOB_SOON = 2;
    static final long EVERY_MS = 15 * 60 * 1000L;
    static final long SOON_MS = 2 * 60 * 1000L;

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
            keepTime(context, settings);
        } catch (SecurityException e) {
            Log.w(TAG, "no WRITE_SECURE_SETTINGS, grant it over ADB: " + e.getMessage());
        }
    }

    /**
     * A TV can come back from a restart with its clock months behind (July 19, on October 25 2026).
     * The private DNS is DNS over TLS to AdGuard, TLS can't check a certificate against a clock that
     * far out, so nothing resolves, and the clock can't put itself right without looking up a time
     * server: every app on the TV says there's no connection. So while the clock is earlier than
     * this app was built, the private DNS steps aside to opportunistic (the router's DNS, encrypted
     * if it can be), the clock gets a nudge to sync, and a run two minutes later puts AdGuard back
     * once the time is right. It only puts back what it parked itself: a private DNS someone changed
     * on purpose stays the way they left it
     */
    static void keepTime(Context context, ContentResolver settings) {
        File parked = new File(context.getFilesDir(), "dns-parked");
        boolean wrong = System.currentTimeMillis() < Built.AT;
        String mode = Settings.Global.getString(settings, "private_dns_mode");
        if (wrong && "hostname".equals(mode)) {
            try {
                new FileOutputStream(parked).close();
            } catch (IOException e) {
                Log.w(TAG, "couldn't note the private DNS as parked: " + e.getMessage());
                return;
            }
            Settings.Global.putString(settings, "private_dns_mode", "opportunistic");
            nudgeClock(settings);
            soon(context);
            Log.i(TAG, "clock is behind, private DNS parked on opportunistic until it syncs");
        } else if (wrong && parked.exists()) {
            nudgeClock(settings);
            soon(context);
        } else if (!wrong && parked.exists()) {
            if ("opportunistic".equals(mode)) {
                Settings.Global.putString(settings, "private_dns_mode", "hostname");
                Log.i(TAG, "clock is right again, private DNS back on its hostname");
            }
            if (!parked.delete()) {
                Log.w(TAG, "couldn't clear the parked note");
            }
        }
    }

    /** Switching automatic time off and on should send Android to its time server again */
    static void nudgeClock(ContentResolver settings) {
        Settings.Global.putInt(settings, "auto_time", 0);
        Settings.Global.putInt(settings, "auto_time", 1);
    }

    static void schedule(Context context) {
        JobScheduler jobs = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        JobInfo job = new JobInfo.Builder(JOB, new ComponentName(context, Job.class))
                .setPeriodic(EVERY_MS)
                .setPersisted(true)
                .build();
        jobs.schedule(job);
    }

    /** One more look in two minutes, for the clock to have synced by */
    static void soon(Context context) {
        JobScheduler jobs = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        jobs.schedule(new JobInfo.Builder(JOB_SOON, new ComponentName(context, Job.class))
                .setMinimumLatency(SOON_MS)
                .build());
    }
}
