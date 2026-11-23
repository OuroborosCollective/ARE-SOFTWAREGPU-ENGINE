Shader "ARE/ProbeColor"
{
    Properties { _DrawColor ("Draw color", Color) = (1,0,0,1) }
    SubShader
    {
        Pass
        {
            Cull Off ZWrite Off ZTest Always
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            float4 _DrawColor;
            float4 vert(float4 position : POSITION) : SV_POSITION { return float4(position.xy, 0.5, 1); }
            float4 frag() : SV_Target { return _DrawColor; }
            ENDHLSL
        }
    }
}
