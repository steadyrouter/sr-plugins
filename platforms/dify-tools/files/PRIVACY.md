# Privacy

This plugin sends your requests to SteadyRouter (`api.steadyrouter.com`), so that the model you choose can make the image or video.

**What is sent**: your prompts, any reference images or starting images you provide, the settings you choose, and your SteadyRouter API key to identify your account.

**Who receives it**: SteadyRouter, which forwards the request to the upstream provider that serves the model. SteadyRouter's own handling of your data is described in its [Privacy Policy]({{privacy_url}}).

**Other requests the plugin makes**: it reads the public model list from `www.steadyrouter.com`, which carries no user data, and it downloads the finished files from the storage links in the reply, without your key.

**What the plugin stores**: nothing. Finished files are handed straight to Dify, which stores them. The plugin keeps no copy, collects no analytics, and does not log your key. Dify stores the key in its own credential system.

Questions: {{contact}}
