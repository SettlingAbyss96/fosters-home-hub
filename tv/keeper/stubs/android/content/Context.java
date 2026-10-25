package android.content;

// abstract on Android; concrete here so the stand-in Activity and JobService don't have to say so
public abstract class Context {
    public static final String JOB_SCHEDULER_SERVICE = "jobscheduler";

    public ContentResolver getContentResolver() {
        throw new RuntimeException("stub");
    }

    public Object getSystemService(String name) {
        throw new RuntimeException("stub");
    }

    public java.io.File getFilesDir() {
        throw new RuntimeException("stub");
    }
}
