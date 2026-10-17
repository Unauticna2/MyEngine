#version 120
#ifdef GL_ARB_shader_texture_lod
#extension GL_ARB_shader_texture_lod : enable
#endif
uniform sampler2D baseTexture;
uniform int hasTexture;
uniform float opacity;
uniform float alphaCutoff;
uniform int alphaMode;
uniform vec3 cameraPosition;
uniform float metallic;
uniform float roughness;
uniform float reflectionStrength;
uniform samplerCube environmentMap;
uniform int reflectionReady;
uniform vec3 reflectionCenter;
uniform float reflectionDistance;
uniform float reflectionMaxLod;
varying vec3 worldPosition;
varying vec3 worldNormal;
varying vec4 tintColor;
varying vec2 texcoord;
// SHADOW_HELPERS
// LIGHT_HELPERS
vec3 sceneReflection(vec3 origin,vec3 direction){
 if(reflectionReady==0)return vec3(0.0);
 // Box projection reduces translation error around the shared local probe.
 vec3 delta=origin-reflectionCenter;
 if(max(abs(delta.x),max(abs(delta.y),abs(delta.z)))<reflectionDistance){
  vec3 safe=vec3(direction.x>=0.0?max(direction.x,.00001):min(direction.x,-.00001),
                 direction.y>=0.0?max(direction.y,.00001):min(direction.y,-.00001),
                 direction.z>=0.0?max(direction.z,.00001):min(direction.z,-.00001));
  vec3 farHit=max((-vec3(reflectionDistance)-delta)/safe,(vec3(reflectionDistance)-delta)/safe);
  float distance=min(farHit.x,min(farHit.y,farHit.z));
  direction=normalize(delta+direction*distance);
 }
 #ifdef GL_ARB_shader_texture_lod
 return textureCubeLod(environmentMap,direction,roughness*roughness*reflectionMaxLod).rgb;
 #else
 // GL 2.1 fallback: angular samples also blur flat-shaded faces whose
 // direction derivatives would otherwise force mip level zero.
 vec3 tangent=normalize(cross(abs(direction.y)>.9?vec3(1,0,0):vec3(0,1,0),direction));
 vec3 bitangent=cross(direction,tangent);float spread=roughness*roughness*.6;
 vec3 sample=textureCube(environmentMap,direction,roughness*5.0).rgb*.2;
 sample+=textureCube(environmentMap,normalize(direction+tangent*spread),roughness*5.0).rgb*.2;
 sample+=textureCube(environmentMap,normalize(direction-tangent*spread),roughness*5.0).rgb*.2;
 sample+=textureCube(environmentMap,normalize(direction+bitangent*spread),roughness*5.0).rgb*.2;
 sample+=textureCube(environmentMap,normalize(direction-bitangent*spread),roughness*5.0).rgb*.2;
 return sample;
 #endif
}
void main(){
 vec4 color=tintColor;
 if(hasTexture!=0)color*=texture2D(baseTexture,texcoord);
 color.a*=opacity;
 if(alphaMode==1 && color.a<=alphaCutoff || alphaMode==2 && color.a<=.00001)discard;
 if(alphaMode!=2)color.a=1.0;
 vec3 n=normalize(worldNormal);vec3 l=normalize(lightDirection);
 vec3 diffuse=color.rgb*lightingAt(worldPosition,n);
 if(metallic<=.0001){gl_FragColor=vec4(diffuse,color.a);return;}
 vec3 view=normalize(cameraPosition-worldPosition);if(dot(n,view)<0.0)n=-n;
 float ndv=max(dot(n,view),.0001);vec3 halfVector=normalize(l+view);
 float exponent=mix(160.0,5.0,roughness*roughness);
 vec3 highlight=pow(max(dot(n,halfVector),0.0),exponent)*lightingAt(worldPosition,n);
 vec3 f0=clamp(color.rgb,.02,1.0);vec3 fresnel=f0+(vec3(1.0)-f0)*pow(1.0-ndv,5.0);
 vec3 environment=vec3(0.0);
 if(reflectionStrength>.0001)environment=sceneReflection(worldPosition+n*.005,reflect(-view,n))*reflectionStrength;
 vec3 metalColor=environment*fresnel+highlight*f0*(.5-.25*roughness)+color.rgb*.025;
 gl_FragColor=vec4(mix(diffuse,metalColor,metallic),color.a);
}
