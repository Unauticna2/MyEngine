uniform int lightCount;
uniform int legacyLight;
uniform int shadowLight;
uniform vec3 ambientLight;
uniform vec3 lightDirection;
uniform vec3 lampPosition[16];
uniform vec3 lampDirection[16];
uniform vec3 lampColor[16];
uniform vec4 lampData[16]; // type, range, inner cosine, outer cosine

vec3 lightingAt(vec3 p,vec3 n){
 vec3 result=ambientLight;
 if(legacyLight!=0){
  vec3 l=normalize(lightDirection);
  result=vec3(clamp(.6+.4*dot(n,l),.2,1.0)*mix(.35,1.0,visibilityAt(p,n,l)));
 }
 for(int i=0;i<16;i++){
  if(i>=lightCount)break;
  vec3 l=-lampDirection[i];float attenuation=1.0;
  if(lampData[i].x>.5){
   vec3 delta=lampPosition[i]-p;float distance=length(delta);
   l=delta/max(distance,.00001);
   attenuation=pow(max(0.0,1.0-distance/lampData[i].y),2.0);
   if(lampData[i].x>1.5){
    float cone=clamp((dot(-l,lampDirection[i])-lampData[i].w)/max(.00001,lampData[i].z-lampData[i].w),0.0,1.0);
    attenuation*=cone*cone*(3.0-2.0*cone);
   }
  }
  if(i==shadowLight)attenuation*=visibilityAt(p,n,l);
  result+=lampColor[i]*max(0.0,dot(n,l))*attenuation;
 }
 // Signed colors/intensities are added before framebuffer clamping.
 return result;
}
