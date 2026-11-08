VARYING vec3 modelWorldPosition;
void MAIN()
{
    modelWorldPosition = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}
