// Drag and drop for file upload
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file');
    const fileLabel = fileInput?.parentElement;
    
    if (fileLabel) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            fileLabel.addEventListener(eventName, preventDefaults, false);
        });
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        ['dragenter', 'dragover'].forEach(eventName => {
            fileLabel.addEventListener(eventName, () => fileLabel.style.borderColor = '#4F46E5');
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            fileLabel.addEventListener(eventName, () => fileLabel.style.borderColor = '#E5E7EB');
        });
        
        fileLabel.addEventListener('drop', function(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            fileInput.files = files;
            fileInput.dispatchEvent(new Event('change'));
        });
    }
});
