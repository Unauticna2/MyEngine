#version 120
uniform sampler2D baseTexture;
uniform int hasTexture;
uniform int alphaMode;
uniform float opacity;
uniform float alphaCutoff;
varying vec2 texcoord;
void main(){
 if(alphaMode==1 && opacity*(hasTexture!=0?texture2D(baseTexture,texcoord).a:1.0)<=alphaCutoff)discard;
 gl_FragColor=vec4(1);
}
