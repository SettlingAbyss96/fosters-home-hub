package android.app;

import android.content.Context;
import android.os.Bundle;

public abstract class Activity extends Context {
    protected void onCreate(Bundle savedInstanceState) {
        throw new RuntimeException("stub");
    }

    public void finish() {
        throw new RuntimeException("stub");
    }
}
