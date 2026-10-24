package home.hub.tvkeeper;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** At boot, and when this app is updated: put things back, and make sure the 15-minute job is there */
public final class Boot extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Keeper.enforce(context);
        Keeper.schedule(context);
    }
}
