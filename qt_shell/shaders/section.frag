VARYING vec3 modelWorldPosition;
void MAIN()
{
    if (clipActive && dot(modelWorldPosition, clipNormal) > clipDistance)
        discard;
    BASE_COLOR = vec4(tint.rgb, alphaValue);
    ROUGHNESS = 0.5;
    METALNESS = 0.2;
}
