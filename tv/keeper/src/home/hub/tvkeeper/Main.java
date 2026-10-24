package home.hub.tvkeeper;

import android.app.Activity;
import android.os.Bundle;

/**
 * No screen. Opened once by tools/tv.py install-keeper: Android doesn't deliver BOOT_COMPLETED to an
 * app that has never been started, so this is the start, and it schedules the job straight away
 */
public final class Main extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Keeper.enforce(this);
        Keeper.schedule(this);
        finish();
    }
}
