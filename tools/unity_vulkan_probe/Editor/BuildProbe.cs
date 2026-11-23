using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildProbe
{
    public static void Build()
    {
        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneLinux64, false);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneLinux64, new[] { GraphicsDeviceType.Vulkan });
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene);
        new GameObject("ARE graphics probe").AddComponent<AreFrameProbe>();
        EditorSceneManager.SaveScene(scene, "Assets/Probe.unity");
        var output = System.Environment.GetEnvironmentVariable("ARE_UNITY_PLAYER");
        if (string.IsNullOrEmpty(output))
            throw new System.ArgumentException("ARE_UNITY_PLAYER must name an isolated executable path");
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        var result = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { "Assets/Probe.unity" }, locationPathName = output,
            target = BuildTarget.StandaloneLinux64, options = BuildOptions.None
        });
        if (result.summary.result != BuildResult.Succeeded)
            throw new System.InvalidOperationException("Linux Vulkan player build failed");
    }
}
