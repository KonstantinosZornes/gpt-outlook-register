import http from './request'

export const getSmsSuccessRate = () => http.get('/api/sms/success-rate')
