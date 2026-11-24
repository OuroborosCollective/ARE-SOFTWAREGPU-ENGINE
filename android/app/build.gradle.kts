plugins { id("com.android.application") }

// A release's public version is shared with the desktop tag. Bounded digits keep
// versionCode unique and ordered across patch/minor/major upgrades and retries.
val releaseVersion = providers.gradleProperty("areReleaseVersion").orNull
val releaseSource = providers.gradleProperty("areSourceSha").orNull
val releaseRequested = gradle.startParameter.taskNames.any { it.contains("release", ignoreCase = true) }
require(!releaseRequested || (releaseVersion != null && releaseSource != null)) {
    "Release builds require -PareReleaseVersion=X.Y.Z and -PareSourceSha=<40-hex>"
}
require((releaseVersion == null) == (releaseSource == null)) { "Version and source must be supplied together" }
val versionParts = (releaseVersion ?: "0.0.1").also {
    require(it.matches(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)"))) { "Invalid release SemVer" }
}.split('.').map { it.toLong() }
val computedCode = versionParts[0] * 10_000_000 + versionParts[1] * 100_000 + versionParts[2]
require(versionParts[0] <= 209 && versionParts[1] <= 99 && versionParts[2] <= 99999 && computedCode in 1..2_100_000_000L) {
    "Version exceeds Android's documented versionCode bounds"
}
require(releaseSource == null || releaseSource.matches(Regex("[0-9a-f]{40}"))) { "Invalid source SHA" }

val metadataDirectory = layout.buildDirectory.dir("generated/areReleaseAssets")
val generateAreReleaseMetadata by tasks.registering {
    inputs.property("version", releaseVersion ?: "0.0.1")
    inputs.property("source", releaseSource ?: "development")
    outputs.dir(metadataDirectory)
    doLast {
        val directory = metadataDirectory.get().asFile
        directory.mkdirs()
        directory.resolve("are-release.json").writeText(
            """{"schema":"are.android-source.v1","version":"${releaseVersion ?: "0.0.1"}","version_code":$computedCode,"source_sha":"${releaseSource ?: "development"}","runtime":"https-companion"}""" + "\n"
        )
    }
}

android {
    namespace = "de.arelorian.softwaregpu"
    compileSdk = 35
    defaultConfig {
        applicationId = "de.arelorian.softwaregpu"
        minSdk = 26
        targetSdk = 35
        versionCode = computedCode.toInt()
        versionName = releaseVersion ?: "0.0.1"
    }
    buildTypes {
        getByName("debug") { isMinifyEnabled = false }
        getByName("release") {
            isDebuggable = false
            isMinifyEnabled = false
            // Signed externally by apksigner; no debug-key fallback.
        }
    }
    sourceSets.getByName("main").assets.srcDir(metadataDirectory)
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
}
tasks.named("preBuild").configure { dependsOn(generateAreReleaseMetadata) }
