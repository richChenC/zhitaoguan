VARYING vec3 modelWorldPosition;
void MAIN()
{
    if (clipActive && dot(modelWorldPosition, clipNormal) > clipDistance)
        discard;
    BASE_COLOR = vec4(tint.rgb, alphaValue);
    ROUGHNESS = roughnessValue;
    METALNESS = metalnessValue;
    EMISSIVE_COLOR = emissiveTint.rgb * emissiveIntensity;
}
void POST_PROCESS()
{
    COLOR_SUM.rgb *= exposureValue;
}
