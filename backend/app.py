from flask import Flask, request, jsonify, make_response
from flask_restplus import Api, Resource, fields
import torch
from transformers import BertTokenizer, BertForQuestionAnswering
from doc import *

import os

from doc import getReqData, preprocess_question
# running Translate API
from googleapiclient.discovery import build

#APIKEYS
APIKEY = os.getenv("api_keys")
service = build('translate', 'v2', developerKey=APIKEY)

def thaitoengtranslation(inputList):
	language = 'en'
	for i in inputList[0]:
		if (i >= 'ก'):
			language = 'th'
			break
	if(language == 'th'):
		outputs = service.translations().list(source=language, target='en', q=inputList).execute()
		tmp = []
		for output in outputs['translations']:
			tmp.append(output['translatedText'])
	else :
		tmp = inputList
	return (tmp,language)

def engtothaitranslation(inputList,language): 
	if (language == 'en'):
		tmp = inputList
	else :
		outputs = service.translations().list(source='en', target=language, q=inputList).execute()
		tmp = []
		for output in outputs['translations']:
			tmp.append(output['translatedText'])
	return tmp

model = BertForQuestionAnswering.from_pretrained('bert-large-uncased-whole-word-masking-finetuned-squad')
torch_device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = model.to(torch_device)
model.eval()
tokenizer = BertTokenizer.from_pretrained('bert-large-uncased-whole-word-masking-finetuned-squad')

def predict(question,context,max_length,stride):
	len_question = len(tokenizer.encode(question))
	input_dict = tokenizer.encode_plus(question,context,max_length=max_length,stride=stride,return_overflowing_tokens=True,
										truncation_strategy='only_second')
	input_ids = [input_dict['input_ids']]
	token_ids = [input_dict['token_type_ids']]

	while 'overflowing_tokens' in input_dict:
		input_dict = tokenizer.encode_plus(tokenizer.encode(question, add_special_tokens=False),
											input_dict['overflowing_tokens'],max_length=max_length,stride=stride,
											return_overflowing_tokens=True,truncation_strategy='only_second',
											is_pretokenized=True,pad_to_max_length=True)

	with torch.no_grad():
		outputs = model(torch.tensor(input_ids), token_type_ids = torch.tensor(token_ids))

	answer = (-float('inf'),'')
	for i in range(len(input_ids)):
		start, end = outputs[0][i].detach().cpu().tolist(), outputs[1][i].detach().cpu().tolist()
		start_index_and_score = sorted([i[::-1] for i in enumerate(start) if len_question < i[0] < max_length-1])[::-1][:5]
		end_index_and_score = sorted([i[::-1] for i in enumerate(end) if len_question < i[0] < max_length-1])[::-1][:5]
		for e in start_index_and_score:
			for c in end_index_and_score:
				if e[1] < c[1] and c[1]-e[1] < 20 and e[0]+c[0] > answer[0]:
					text = tokenizer.decode(input_ids[i][e[1]:c[1]+1])
					text = text.replace('[SEP]','')
					text = text.replace('[PAD]','')
					answer = (e[0]+c[0],text)
	return answer

flask_app = Flask(__name__)
app = Api(app = flask_app, 
		  version = "1.0", 
		  title = "Covid-19 Question Answering", 
		  description = "Predict results using a bert model pretrained on SQuAD")

name_space = app.namespace('prediction')

swagger = app.model('Prediction params', 
				  {'Question': fields.String(required = True, 
				  							   description="Question", 
    					  				 	   help="Question cannot be blank")})

# classifier = joblib.load('classifier.joblib')

def getAnswers(tenbestresults, Question):
	answers = []
	pdf, iddict = getReqData()

	for i,rs in (enumerate(tenbestresults)):
  		pp_id = iddict[rs[1]]
  		text = pdf[pp_id]['context']
  		answers.append(predict(Question,text,256,32))
		  
	answers = sorted(answers)[::-1][:3]

	return answers

def selectAnswers(answers):
	results = []
	for answer in answers:
		results.append(answer[1])
	return results
	

@name_space.route("/")
class MainClass(Resource):

	def options(self):
		response = make_response()
		response.headers.add("Access-Control-Allow-Origin", "*")
		response.headers.add('Access-Control-Allow-Headers', "*")
		response.headers.add('Access-Control-Allow-Methods', "*")
		return response

	@app.expect(swagger)		
	def post(self):
		try: 
			formData = request.json
			question = [val for val in formData.values()]
			# print(question)
			question,language = thaitoengtranslation(question)
			question = question[0]
			# print(question,'lang:',language)
			tenbestdocs = preprocess_question(question)

			data = getAnswers(tenbestdocs, question)
			print(data)
			# print(tenbestdocs)
			data = selectAnswers(data)
			data = engtothaitranslation(data,language)
			# print(output)

			response = jsonify({
				"statusCode": 200,
				"status": "Prediction made",
				"result": data
				})
			response.headers.add('Access-Control-Allow-Origin', '*')
			return response
		except Exception as error:
			return jsonify({
				"statusCode": 500,
				"status": "Could not make prediction",
				"error": str(error)
			})