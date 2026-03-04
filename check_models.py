from google import genai
client = genai.Client(api_key="AIzaSyC0VtmX-hSf2lOAYmC8e3-Wy0yQNeA7J_Q")

for model in client.models.list():
    print(model.name)