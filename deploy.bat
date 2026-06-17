@echo off
echo =========================================
echo  Deploying Yaa Core to Streamlit Cloud...
echo =========================================
git add .
git commit -m "Auto-deploy update"
git push origin main
echo =========================================
echo  Pushed successfully! Streamlit Cloud will
echo  rebuild and deploy the app in 1-2 mins.
echo =========================================
pause
