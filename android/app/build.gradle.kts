plugins { id("com.android.application") }
android {
    namespace = "de.arelorian.softwaregpu"
    compileSdk = 35
    defaultConfig { applicationId = "de.arelorian.softwaregpu"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "1.0" }
    buildTypes { getByName("debug") { isMinifyEnabled = false } }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
