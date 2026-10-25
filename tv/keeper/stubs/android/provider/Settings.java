package android.provider;

import android.content.ContentResolver;

public final class Settings {
    public static final class Global {
        public static int getInt(ContentResolver cr, String name, int def) {
            throw new RuntimeException("stub");
        }

        public static boolean putInt(ContentResolver cr, String name, int value) {
            throw new RuntimeException("stub");
        }

        public static String getString(ContentResolver cr, String name) {
            throw new RuntimeException("stub");
        }

        public static boolean putString(ContentResolver cr, String name, String value) {
            throw new RuntimeException("stub");
        }

        public static long getLong(ContentResolver cr, String name, long def) {
            throw new RuntimeException("stub");
        }

        public static boolean putLong(ContentResolver cr, String name, long value) {
            throw new RuntimeException("stub");
        }
    }
}
