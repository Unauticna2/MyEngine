#version 120
uniform mat4 inverseView;
varying vec3 worldPosition;
varying vec3 worldNormal;
varying vec4 tintColor;
varying vec2 texcoord;
void main(){
 vec4 eye=gl_ModelViewMatrix*gl_Vertex;
 worldPosition=(inverseView*eye).xyz;
 worldNormal=mat3(inverseView)*(gl_NormalMatrix*gl_Normal);
 tintColor=gl_Color;texcoord=gl_MultiTexCoord0.xy;
 gl_Position=gl_ProjectionMatrix*eye;
}
