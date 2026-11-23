using System;
using UnityEngine;
using UnityEngine.Rendering;

public class AreFrameProbe : MonoBehaviour
{
    void Start()
    {
        Debug.Log("ARE_UNITY_DEVICE api=" + SystemInfo.graphicsDeviceType +
                  " name=" + SystemInfo.graphicsDeviceName + " version=" + SystemInfo.graphicsDeviceVersion);
        if (SystemInfo.graphicsDeviceType != GraphicsDeviceType.Vulkan ||
            !SystemInfo.graphicsDeviceName.StartsWith("ARE SoftwareGPU", StringComparison.Ordinal))
        {
            Application.Quit(31);
            return;
        }
        var shader = Resources.Load<Shader>("ProbeColor");
        if (shader == null || !shader.isSupported) { Application.Quit(32); return; }
        var material = new Material(shader);
        var mesh = new Mesh();
        mesh.vertices = new[] { new Vector3(-1,-1,0), new Vector3(1,-1,0), new Vector3(-1,1,0) };
        mesh.triangles = new[] { 0,1,2 };
        var target = new RenderTexture(32, 32, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
        var readback = new Texture2D(32, 32, TextureFormat.RGBA32, false, true);
        var previous = RenderTexture.active;
        int result = 33;
        try
        {
            if (!target.Create()) throw new InvalidOperationException("Offscreen target creation failed");
            foreach (var color in new[] { Color.red, Color.green })
            {
                material.SetColor("_DrawColor", color);
                using (var cmd = new CommandBuffer())
                {
                    cmd.SetRenderTarget(target);
                    cmd.ClearRenderTarget(false, true, Color.black);
                    cmd.DrawMesh(mesh, Matrix4x4.identity, material);
                    Graphics.ExecuteCommandBuffer(cmd);
                }
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0,0,32,32), 0, 0);
                var bytes = readback.GetPixels32();
                int colored = 0, black = 0;
                foreach (var pixel in bytes)
                {
                    if (pixel.r < 5 && pixel.g < 5 && pixel.b < 5) ++black;
                    else if (Math.Abs(pixel.r - color.r*255) <= 2 &&
                             Math.Abs(pixel.g - color.g*255) <= 2 && pixel.b <= 2) ++colored;
                }
                if (colored < 460 || black < 460 || colored + black != bytes.Length)
                    throw new InvalidOperationException("Triangle framebuffer readback failed");
            }
            Debug.Log("ARE_UNITY_TWO_TRIANGLE_READBACKS_PASS");
            result = 0;
        }
        catch (Exception ex) { Debug.LogException(ex); }
        finally
        {
            RenderTexture.active = previous;
            target.Release();
            Destroy(target); Destroy(readback); Destroy(material); Destroy(mesh);
            Application.Quit(result);
        }
    }
}
