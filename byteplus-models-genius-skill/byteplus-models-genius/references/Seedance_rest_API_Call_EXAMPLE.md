curl -X POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -d '{
    "model": "dreamina-seedance-2-0-260128",
    "content": [
         {
            "type": "text",
            "text": "Use the first-person POV framing from Video 1 throughout, and use Audio 1 as the background music throughout. First-person POV fruit tea promotional ad, Seedance brand limited-edition apple fruit tea; opening frame is Image 1, your hand picks a dew-covered Aksu red apple, a light, crisp apple tapping sound; 2–4 seconds: fast cuts, your hand drops apple chunks into a shaker, adds ice and tea base, shakes forcefully, ice clinking and shaking sounds sync with upbeat rhythmic beats, background audio: {Fresh-cut, shaken fresh}; 4–6 seconds: first-person close-up of the finished drink, layered fruit tea is poured into a clear cup, your hand gently squeezes milk foam to spread across the top, a pink brand sticker is applied to the cup, the camera moves closer to show the layered textures of the foam and fruit tea; 6–8 seconds: first-person hand-held toast shot, you raise the fruit tea from Image 2 toward the camera (simulating handing it to the viewer), the cup label is clearly visible, background audio {Take a sip of fresh refreshment}, the final frame freezes on Image 2. All background voice audio uses a female voice."
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic1.jpg"
            },
            "role": "reference_image"
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_image/r2v_tea_pic2.jpg"
            },
            "role": "reference_image"
        },
        {
          "type": "video_url",
          "video_url": {
              "url": "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_video/r2v_tea_video1.mp4"
          },
          "role": "reference_video"
        },
        {
          "type": "audio_url",
          "audio_url": {
              "url": "https://ark-doc.tos-ap-southeast-1.bytepluses.com/doc_audio/r2v_tea_audio1.mp3"
          },
          "role": "reference_audio"
        }
    ],
    "generate_audio":true,
    "ratio": "16:9",
    "duration": 11,
    "watermark": false
}'